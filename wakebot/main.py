from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .alerts import AlertInputs, Notifier, maybe_alert
from .config import Config
from .discovery import ds_search_native_pairs
from .gecko import GeckoCache
from .net_http import HttpClient
from .storage import Storage


def run_once(cfg: Config) -> None:
    http = HttpClient(cfg)
    storage = Storage(cfg)
    cache = GeckoCache(cfg.gecko_ttl_sec)
    notifier = Notifier(cfg)

    print(f"Wake-up bot started. Chains: {', '.join(cfg.chains)}")
    print(f"Save candidates: {cfg.save_candidates} -> {cfg.candidates_path}")
    if cfg.max_cycles:
        print(f"Max cycles: {cfg.max_cycles}")

    cycle_started = time.monotonic()
    total_scanned = 0
    total_cands = 0

    chain_results: list[tuple[str, list[dict], int]] = []

    if cfg.chains:
        max_workers = min(len(cfg.chains), cfg.chain_scan_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_chain = {pool.submit(ds_search_native_pairs, cfg, http, chain): chain for chain in cfg.chains}
            for fut in as_completed(future_to_chain):
                chain_name = future_to_chain[fut]
                try:
                    cands, scanned = fut.result()
                    chain_results.append((chain_name, cands, scanned))
                except Exception as e:
                    print(f"[{chain_name}] error: {e}")

    # order by configured order
    if len(chain_results) > 1:
        order = {c: i for i, c in enumerate(cfg.chains)}
        chain_results.sort(key=lambda x: order.get(x[0], 0))

    aggregated: list[dict] = []
    for chain_name, cands, scanned in chain_results:
        total_scanned += scanned
        total_cands += len(cands)
        aggregated.extend(cands)

    # log candidates in JSONL if enabled
    if aggregated and cfg.save_candidates:
        now_iso = datetime.now(timezone.utc).isoformat()
        for rec in aggregated:
            out = dict(rec)
            out["ts"] = now_iso
            storage.append_jsonl(out)

    # prefetch Gecko for candidates that already pass DS precheck
    prechecked: list[dict] = []
    for meta in aggregated:
        v1 = float(meta.get("vol1h_ds") or 0.0)
        v48 = float(meta.get("vol48h_ds") or 0.0)
        prev48 = max(v48 - v1, 0.0)
        if v1 > 0 and v1 > prev48:
            prechecked.append(meta)

    if prechecked:
        workers = min(len(prechecked), cfg.alert_fetch_workers)
        if workers:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_fetch_gecko_wrapped, cfg, http, cache, m): m for m in prechecked}
                for fut in as_completed(futures):
                    m = futures[fut]
                    try:
                        m["_gecko_data"] = fut.result()
                    except Exception:
                        m["_gecko_data"] = (0.0, 0, 0.0)

    for meta in prechecked:
        g = meta.get("_gecko_data")
        def fetch_gecko(chain: str, pool: str):
            if g is not None:
                return g
            # fallback
            from .gecko import fetch_gecko_metrics
            return fetch_gecko_metrics(cfg, http, chain, pool, cache)

        inputs = AlertInputs(
            chain=meta["chain"],
            pool=meta["pool"],
            url=meta.get("url", ""),
            token_symbol=meta.get("baseSymbol", ""),
            token_addr=meta.get("baseAddr", ""),
            fdv=float(meta.get("fdv", 0.0)),
            ds_vol1h=float(meta.get("vol1h_ds", 0.0)),
            ds_vol48h=float(meta.get("vol48h_ds", 0.0)),
        )
        maybe_alert(cfg, storage, cache, fetch_gecko, notifier, inputs)

    elapsed = time.monotonic() - cycle_started
    print(f"[cycle] scanned total: {total_scanned}, candidates total: {total_cands}, took {elapsed:.2f}s")


def _fetch_gecko_wrapped(cfg: Config, http: HttpClient, cache: GeckoCache, meta: dict):
    from .gecko import fetch_gecko_metrics
    return fetch_gecko_metrics(cfg, http, meta["chain"], meta["pool"], cache)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run single cycle and exit")
    args = parser.parse_args(argv)

    cfg = Config.load()

    cycle_idx = 0
    if args.once:
        run_once(cfg)
        return

    while True:
        cycle_idx += 1
        run_once(cfg)
        if cfg.max_cycles and cycle_idx >= cfg.max_cycles:
            print(f"[cycle] reached MAX_CYCLES={cfg.max_cycles}, stopping loop")
            break
        # sleep happens inside run_once balancing elapsed, so here just continue


if __name__ == "__main__":
    main()
