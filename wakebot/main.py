from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .alerts import AlertInputs, Notifier, maybe_alert, build_revival_text, should_revival
from .config import Config
from .discovery import gt_discover_candidates
from .gecko import GeckoCache, fetch_ohlcv_49h, fetch_revival_window
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
    total_filtered_tx = 0
    total_filtered_liq = 0

    # start cycle accounting for HTTP
    http.reset_cycle_counters()

    # discovery across chains using configured sources and progress cursors
    aggregated: list[dict] = []
    if cfg.chains:
        # limit chain scan workers
        max_workers = min(len(cfg.chains), cfg.chain_scan_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for chain in cfg.chains:
                futures[pool.submit(gt_discover_candidates, cfg, http, storage, chain, cycle_idx=cycle_idx)] = chain
            for fut in as_completed(futures):
                chain_name = futures[fut]
                try:
                    items = fut.result()
                    aggregated.extend(items or [])
                except Exception as e:
                    print(f"[{chain_name}] discovery error: {e}")

    # log candidates in JSONL if enabled
    if aggregated and cfg.save_candidates:
        now_iso = datetime.now(timezone.utc).isoformat()
        for rec in aggregated:
            out = dict(rec)
            out["ts"] = now_iso
            storage.append_jsonl(out)

    # Compute dynamic budget for OHLCV probes
    theoretical_cycle_budget = int(cfg.gecko_calls_per_min * (cfg.loop_seconds / 60.0))
    spent_so_far = http.get_cycle_requests() + http.get_cycle_penalty()
    available_for_ohlcv = max(0, theoretical_cycle_budget - spent_so_far - cfg.gecko_safety_budget)
    ohlcv_budget = min(available_for_ohlcv, cfg.max_ohlcv_probes_cap)
    if available_for_ohlcv > 0:
        ohlcv_budget = max(cfg.min_ohlcv_probes, ohlcv_budget)
    else:
        ohlcv_budget = 0
    print(
        f"[budget] theoretical={theoretical_cycle_budget}, spent={spent_so_far}, "
        f"avail_ohlcv={available_for_ohlcv}, cap={cfg.max_ohlcv_probes_cap}, final_ohlcv_budget={ohlcv_budget}"
    )

    # seen-cache per chain to avoid wasting OHLCV budget on recently probed pools
    recently_seen_by_chain: dict[str, set[str]] = {}
    with storage.get_conn() as conn:
        for chain in cfg.chains:
            recently_seen_by_chain[chain] = storage.get_recently_seen(conn, chain, cfg.seen_ttl_min)
    candidates = [m for m in aggregated if m.get("pool") not in recently_seen_by_chain.get(m.get("chain"), set())]
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
    selected = candidates[: ohlcv_budget] if ohlcv_budget > 0 else []

    # parallel fetch + alerts
    if selected:
        workers = max(1, min(len(selected), cfg.alert_fetch_workers))
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
                # Each worker fetches revival window and possibly sends alert
                def _work(inp: AlertInputs, pool_created_at: str | None):
                    # Cooldown
                    with storage.get_conn() as conn:
                        last = storage.get_last_alert_ts(conn, inp.pool)
                        if last:
                            last_dt = datetime.fromtimestamp(int(last), tz=timezone.utc)
                            if datetime.now(timezone.utc) - last_dt < timedelta(minutes=cfg.cooldown_min):
                                return {"probed": True, "probed_ok": True, "alert": False}

                    # Fetch window
                    w = fetch_revival_window(cfg, http, inp.chain, inp.pool, pool_created_at)
                    # Mark seen regardless of alert outcome
                    with storage.get_conn() as conn:
                        storage.mark_as_seen(conn, inp.chain, inp.pool)

                    if not should_revival(w, cfg):
                        return {"probed": True, "probed_ok": True, "alert": False}

                    # Send alert and set cooldown
                    text = build_revival_text(inp, inp.chain.capitalize(), w)
                    notifier.send(text)
                    with storage.get_conn() as conn:
                        storage.set_last_alert_ts(conn, inp.pool, int(datetime.now(timezone.utc).timestamp()))
                    return {"probed": True, "probed_ok": True, "alert": True}

                futures[pool.submit(_work, inputs, meta.get("pool_created_at"))] = inputs.pool
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
        f"skipped_seen: {skipped_seen}"
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
