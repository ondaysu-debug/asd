from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .alerts import AlertInputs, Notifier, maybe_alert
from .config import Config
from .discovery import gt_fetch_page
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

    # pick sources for this cycle
    active_sources = pick_sources(cfg, cycle_idx)

    # compute budgets
    pages_spent = len(cfg.chains) * cfg.gecko_pages_per_chain * max(1, len(active_sources)) if cfg.gecko_source_mode == "all" else len(cfg.chains) * cfg.gecko_pages_per_chain
    budget = int(cfg.gecko_calls_per_min * cfg.loop_seconds / 60.0)
    ohlcv_budget = max(0, min(cfg.max_ohlcv_probes, budget - pages_spent))

    # discovery across chains/sources/pages
    aggregated: list[dict] = []
    if cfg.chains:
        # limit chain scan workers
        max_workers = min(len(cfg.chains), cfg.chain_scan_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for chain in cfg.chains:
                for source in active_sources:
                    for page in range(1, cfg.gecko_pages_per_chain + 1):
                        futures[pool.submit(gt_fetch_page, cfg, http, chain, source, page)] = (chain, source, page)
            for fut in as_completed(futures):
                chain_name, source, page = futures[fut]
                try:
                    page_items = fut.result() or []
                    aggregated.extend(page_items)
                except Exception as e:
                    print(f"[{chain_name}] {source} page {page} error: {e}")

    total_cands = len(aggregated)

    # log candidates in JSONL if enabled
    if aggregated and cfg.save_candidates:
        now_iso = datetime.now(timezone.utc).isoformat()
        for rec in aggregated:
            out = dict(rec)
            out["ts"] = now_iso
            storage.append_jsonl(out)

    # sort and select OHLCV candidates by liquidity desc
    if aggregated:
        aggregated.sort(key=lambda m: (float(m.get("liquidity", 0.0)), -float(m.get("tx24h", 0))), reverse=True)
    selected = aggregated[:ohlcv_budget] if ohlcv_budget > 0 else []

    # parallel fetch + alerts
    if selected:
        workers = min(len(selected), cfg.alert_fetch_workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
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
                    fut.result()
                except Exception as e:
                    pid = futures[fut]
                    print(f"[alert] {pid} error: {e}")

    print(f"[cycle] scanned total: {total_scanned}, candidates total: {total_cands}")


def pick_sources(cfg: Config, cycle_idx: int) -> list[str]:
    sources = cfg.gecko_sources_list or ["new"]
    if cfg.gecko_source_mode == "rotate":
        i = cycle_idx % max(1, len(sources))
        return [sources[i]]
    return sources


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
