from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .alerts import AlertInputs, Notifier, maybe_alert
from .config import Config
from .discovery import gt_discover_new_pairs
from .gecko import GeckoCache, fetch_ohlcv_49h
from .net_http import HttpClient
from .storage import Storage


def run_once(cfg: Config, *, cycle_idx: int) -> None:
    http = HttpClient(cfg)
    storage = Storage(cfg)
    cache = GeckoCache(cfg.gecko_ttl_sec)
    notifier = Notifier(cfg)

    print(f"Wake-up bot started. Chains: {', '.join(cfg.chains)}")
    print(f"Save candidates: {cfg.save_candidates} -> {cfg.candidates_path}")
    if cfg.max_cycles:
        print(f"Max cycles: {cfg.max_cycles}")

    total_scanned = 0
    total_cands = 0
    total_filtered_tx = 0
    total_filtered_liq = 0

    # discovery across chains using configured sources and pages
    aggregated: list[dict] = []
    if cfg.chains:
        # limit chain scan workers
        max_workers = min(len(cfg.chains), cfg.chain_scan_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for chain in cfg.chains:
                futures[pool.submit(gt_discover_new_pairs, cfg, http, chain)] = chain
            for fut in as_completed(futures):
                chain_name = futures[fut]
                try:
                    items, stats = fut.result()
                    aggregated.extend(items or [])
                    # accumulate scanned pages and filter counters
                    total_scanned += int(stats.get("pages_fetched", 0)) * int(cfg.gecko_page_size)
                    total_filtered_tx += int(stats.get("filtered_tx", 0))
                    total_filtered_liq += int(stats.get("filtered_liq", 0))
                except Exception as e:
                    print(f"[{chain_name}] discovery error: {e}")

    total_cands = len(aggregated)

    # log candidates in JSONL if enabled
    if aggregated and cfg.save_candidates:
        now_iso = datetime.now(timezone.utc).isoformat()
        for rec in aggregated:
            out = dict(rec)
            out["ts"] = now_iso
            storage.append_jsonl(out)

    # seen-cache to avoid wasting OHLCV budget on recently probed pools
    with storage.get_conn() as conn:
        seen = storage.get_recently_seen(conn, cfg.seen_ttl_sec)
    candidates = [m for m in aggregated if m.get("pool") not in seen]
    skipped_seen = max(0, len(aggregated) - len(candidates))

    # sort and cap OHLCV probes by liquidity desc then tx24h desc
    if candidates:
        candidates.sort(
            key=lambda m: (
                float(m.get("liquidity", 0.0)),
                int(m.get("tx24h", 0)),
            ),
            reverse=True,
        )
    selected = candidates[: cfg.max_ohlcv_probes] if cfg.max_ohlcv_probes > 0 else []

    # parallel fetch + alerts
    if selected:
        workers = min(len(selected), cfg.alert_fetch_workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            probed_total = 0
            probed_ok = 0
            for meta in selected:
                inputs = AlertInputs(
                    chain=meta["chain"],
                    pool=meta["pool"],
                    url=meta.get("url", ""),
                    token_symbol=meta.get("baseSymbol", ""),
                    token_addr=meta.get("baseAddr", ""),
                    liquidity=float(meta.get("liquidity", 0.0)),
                )
                futures[pool.submit(maybe_alert, cfg, storage, cache, http, notifier, inputs)] = inputs.pool
            for fut in as_completed(futures):
                # drain exceptions to avoid threadpool suppression
                try:
                    res = fut.result()
                    probed_total += 1
                    if isinstance(res, dict) and res.get("probed_ok"):
                        probed_ok += 1
                except Exception as e:
                    pid = futures[fut]
                    print(f"[alert] {pid} error: {e}")
    else:
        probed_total = 0
        probed_ok = 0

    # purge old seen entries
    with storage.get_conn() as conn:
        storage.purge_seen_older_than(conn, cfg.seen_ttl_sec)

    # cycle summary
    print(
        f"[cycle] candidates total: {len(candidates)}, "
        f"ohlcv_probed: {probed_ok}/{probed_total}, "
        f"skipped_seen: {skipped_seen}, "
        f"filtered_tx: {total_filtered_tx}, filtered_liq: {total_filtered_liq}"
    )
    # optional: scanned_total if useful
    print(f"[cycle] scanned total: {total_scanned}")


def pick_sources(cfg: Config, cycle_idx: int) -> list[str]:
    # Deprecated rotation; always use all configured sources per cycle
    return cfg.gecko_sources_list or ["new"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run single cycle and exit")
    args = parser.parse_args(argv)

    cfg = Config.load()

    cycle_idx = 0
    if args.once:
        run_once(cfg, cycle_idx=cycle_idx)
        return

    while True:
        cycle_idx += 1
        cycle_started = time.monotonic()
        run_once(cfg, cycle_idx=cycle_idx)

        elapsed = time.monotonic() - cycle_started
        sleep_for = max(0.0, cfg.loop_seconds - elapsed)
        print(f"[cycle] cycle complete, sleeping for {sleep_for:.2f}s")
        time.sleep(sleep_for)

        if cfg.max_cycles and cycle_idx >= cfg.max_cycles:
            print(f"[cycle] reached MAX_CYCLES={cfg.max_cycles}, stopping loop")
            break


if __name__ == "__main__":
    main()
