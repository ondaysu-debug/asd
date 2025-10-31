from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from .alerts import (
    AlertInputs,
    Notifier,
    build_revival_text_cmc,
    should_alert_revival_cmc,
)
from .config import Config
from .discovery import cmc_discover_candidates
from .gecko import GeckoCache
from .cmc import fetch_cmc_ohlcv_25h
from .net_http import HttpClient
from .storage import Storage


def health_check(cfg: Config, logger=print) -> bool:
    """
    Offline health check: validates configuration and dependencies without network calls.
    Returns True/False and prints brief report.
    """
    ok = True
    try:
        # 1) Check config essentials
        if not cfg.chains or len(cfg.chains) == 0:
            logger("[health] FAIL: no chains configured")
            ok = False
        else:
            logger(f"[health] chains: {', '.join(cfg.chains)} - OK")
        
        if not cfg.cmc_dex_base:
            logger("[health] FAIL: CMC_DEX_BASE not configured")
            ok = False
        else:
            logger(f"[health] cmc_dex_base: {cfg.cmc_dex_base} - OK")
        
        if not cfg.cmc_api_key:
            logger("[health] WARN: CMC_API_KEY not set (may limit API access)")
        else:
            logger(f"[health] cmc_api_key: ***{cfg.cmc_api_key[-4:]} - OK")
        
        # 2) Check budget params
        if cfg.cmc_calls_per_min <= 0:
            logger("[health] FAIL: CMC_CALLS_PER_MIN must be > 0")
            ok = False
        else:
            logger(f"[health] cmc_calls_per_min: {cfg.cmc_calls_per_min} - OK")
        
        # 3) Check DB path writability
        try:
            db_parent = cfg.db_path.parent
            if not db_parent.exists():
                db_parent.mkdir(parents=True, exist_ok=True)
            logger(f"[health] db_path: {cfg.db_path} - OK")
        except Exception as e:
            logger(f"[health] db_path: {cfg.db_path} - FAIL ({e})")
            ok = False
        
        logger(f"[health] offline check: {'PASS' if ok else 'FAIL'}")
    
    except Exception as e:
        logger(f"[health] error: {type(e).__name__}: {e}")
        ok = False
    
    return ok


def health_check_online(cfg: Config, http: HttpClient, logger=print) -> bool:
    """
    Online health check: mini-ping to CMC API (1 discovery page + 1 OHLCV).
    Returns True/False and prints brief report.
    """
    ok = True
    try:
        # 1) Discovery ping: one page for one chain
        chain = (cfg.chains or ["ethereum"])[0]
        cmc_chain = cfg.chain_slugs.get(chain, chain) if cfg.chain_slugs else chain
        
        # Light discovery call (1 page, limit=5) - CMC DEX v4 with network_slug
        discovery_url = f"{cfg.cmc_dex_base}/spot-pairs/latest?network_slug={cmc_chain}&limit=5"
        try:
            doc = http.cmc_get_json(discovery_url, timeout=10.0) or {}
            ok = ok and bool(doc.get("data"))
            logger(f"[health] discovery on {chain}/{cmc_chain}: {'OK' if doc.get('data') else 'FAIL'}")
        except Exception as e:
            logger(f"[health] discovery on {chain}/{cmc_chain}: FAIL ({e})")
            ok = False
        
        # 2) OHLCV ping (if we got at least 1 pair_id from discovery)
        pair_id = None
        try:
            data = (doc or {}).get("data") or []
            if data:
                # Pick first valid pair/pool id
                first = data[0] if isinstance(data, list) else {}
                pair_id = (
                    first.get("pair_address")
                    or first.get("id")
                    or first.get("pairId")
                    or first.get("pool_id")
                    or first.get("address")
                )
        except Exception:
            pass
        
        if pair_id:
            ohlcv_url = f"{cfg.cmc_dex_base}/pairs/ohlcv/latest?network_slug={cmc_chain}&contract_address={pair_id}&interval=1h&limit=2"
            try:
                ohlcv = http.cmc_get_json(ohlcv_url, timeout=10.0) or {}
                ok = ok and bool(ohlcv.get("data"))
                logger(f"[health] ohlcv for {pair_id}: {'OK' if ohlcv.get('data') else 'FAIL'}")
            except Exception as e:
                logger(f"[health] ohlcv for {pair_id}: FAIL ({e})")
                ok = False
        else:
            logger("[health] skip ohlcv: no pair_id from discovery")
    
    except Exception as e:
        logger(f"[health] error: {type(e).__name__}: {e}")
        ok = False
    
    return ok


def run_once(cfg: Config, *, cycle_idx: int) -> dict:
    """
    Run one discovery+alert cycle.
    Returns dict with health status and stats.
    """
    http = HttpClient(cfg)
    storage = Storage(cfg)
    cache = GeckoCache(cfg.gecko_ttl_sec)
    notifier = Notifier(cfg)

    print(f"Wake-up bot started. Chains: {', '.join(cfg.chains)}")
    print(f"Save candidates: {cfg.save_candidates} -> {cfg.candidates_path}")
    if cfg.max_cycles:
        print(f"Max cycles: {cfg.max_cycles}")

    total_scanned = 0
    cycle_ok = True
    first_error = None

    # ??????? ???????? ????? ????? ???????
    http.reset_cycle_metrics()

    # discovery across chains using configured CMC sources and progress cursors
    aggregated: list[dict] = []
    per_chain_stats: dict[str, dict] = {}
    if cfg.chains:
        # limit chain scan workers
        max_workers = min(len(cfg.chains), cfg.chain_scan_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for chain in cfg.chains:
                futures[pool.submit(cmc_discover_candidates, cfg, http, storage, chain, cycle_idx=cycle_idx)] = chain
            for fut in as_completed(futures):
                chain_name = futures[fut]
                try:
                    items, stats = fut.result()
                    aggregated.extend(items or [])
                    per_chain_stats[chain_name] = stats or {}
                    total_scanned += int((stats or {}).get("scanned_pairs", 0))
                except Exception as e:
                    print(f"[{chain_name}] discovery error: {e}")

    # log candidates in JSONL if enabled
    if aggregated and cfg.save_candidates:
        now_iso = datetime.now(timezone.utc).isoformat()
        for rec in aggregated:
            out = dict(rec)
            out["ts"] = now_iso
            storage.append_jsonl(out)

    # Compute dynamic budget for OHLCV probes (CMC)
    total_budget = int(cfg.cmc_calls_per_min * (cfg.loop_seconds / 60.0))
    discovery_cost = sum(int((per_chain_stats.get(ch, {}) or {}).get("pages_planned", 0)) for ch in (cfg.chains or []))
    spent_so_far = int(http.get_cycle_requests() + http.get_cycle_penalty())
    
    # Reserve 2-3 requests for GT fallback if enabled
    gt_reserve = 0
    if cfg.allow_gt_ohlcv_fallback:
        gt_reserve = 3
    
    base_available = max(0, total_budget - discovery_cost - int(cfg.cmc_safety_budget) - gt_reserve)
    available_for_ohlcv = max(0, base_available - spent_so_far)
    ohlcv_budget = int(min(available_for_ohlcv, cfg.max_ohlcv_probes_cap))
    if available_for_ohlcv > 0:
        ohlcv_budget = int(max(cfg.min_ohlcv_probes, ohlcv_budget))
    else:
        ohlcv_budget = 0
    print(
        f"[budget] total={total_budget}, discovery_cost={discovery_cost}, spent={spent_so_far}, "
        f"gt_reserve={gt_reserve}, avail_ohlcv={available_for_ohlcv}, cap={cfg.max_ohlcv_probes_cap}, final_ohlcv_budget={ohlcv_budget}"
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

    # distribute selection counts per chain for logging
    per_chain_selection: dict[str, int] = {}
    for m in selected:
        ch = m.get("chain")
        per_chain_selection[ch] = per_chain_selection.get(ch, 0) + 1

    # parallel fetch + alerts
    if selected:
        workers = max(1, min(len(selected), cfg.alert_fetch_workers))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            probed_total = 0
            probed_ok = 0
            alerts_by_chain: dict[str, int] = {}
            for meta in selected:
                inputs = AlertInputs(
                    chain=meta["chain"],
                    pool=meta["pool"],
                    url=meta.get("url", ""),
                    token_symbol=meta.get("baseSymbol", ""),
                    token_addr=meta.get("baseAddr", ""),
                    liquidity=float(meta.get("liquidity", 0.0)),
                    pool_created_at=str(meta.get("pool_created_at") or ""),
                )
                # Each worker fetches 25h window (CMC) and possibly sends alert
                def _work(inp: AlertInputs):
                    # Cooldown
                    with storage.get_conn() as conn:
                        last = storage.get_last_alert_ts(conn, inp.pool)
                        if last:
                            last_dt = datetime.fromtimestamp(int(last), tz=timezone.utc)
                            if datetime.now(timezone.utc) - last_dt < timedelta(minutes=cfg.cooldown_min):
                                return {"probed": True, "probed_ok": True, "alert": False, "chain": inp.chain, "source": ""}

                    vol1h, prev24h, ok_age, source = fetch_cmc_ohlcv_25h(cfg, http, inp.chain, inp.pool, cache, inp.pool_created_at)
                    # Mark seen regardless of alert outcome
                    with storage.get_conn() as conn:
                        storage.mark_as_seen(conn, inp.chain, inp.pool)

                    if not should_alert_revival_cmc(vol1h, prev24h, ok_age, cfg):
                        return {"probed": True, "probed_ok": True, "alert": False, "chain": inp.chain, "source": source}
                    
                    # Send alert and set cooldown
                    text = build_revival_text_cmc(inp, inp.chain.capitalize(), vol1h, prev24h, source)
                    notifier.send(text)
                    with storage.get_conn() as conn:
                        storage.set_last_alert_ts(conn, inp.pool, int(datetime.now(timezone.utc).timestamp()))
                    return {"probed": True, "probed_ok": True, "alert": True, "chain": inp.chain, "source": source}

                futures[pool.submit(_work, inputs)] = inputs.pool
            for fut in as_completed(futures):
                # drain exceptions to avoid threadpool suppression
                try:
                    res = fut.result()
                    probed_total += 1
                    if isinstance(res, dict) and res.get("probed_ok"):
                        probed_ok += 1
                        if res.get("alert"):
                            ch = res.get("chain") or "?"
                            alerts_by_chain[ch] = alerts_by_chain.get(ch, 0) + 1
                except Exception as e:
                    pid = futures[fut]
                    print(f"[alert] {pid} error: {e}")
    else:
        probed_total = 0
        probed_ok = 0
        alerts_by_chain = {}

    # purge old seen entries
    with storage.get_conn() as conn:
        storage.purge_seen_older_than(conn, cfg.seen_ttl_sec)

    # per-chain summary
    for chain in cfg.chains:
        scanned_cnt = int((per_chain_stats.get(chain, {}) or {}).get("scanned_pairs", 0))
        cand_cnt = len([m for m in candidates if m.get("chain") == chain])
        probes = int(per_chain_selection.get(chain, 0))
        alerts_cnt = int(alerts_by_chain.get(chain, 0))
        print(f"[cycle] {chain}: scanned={scanned_cnt}, candidates={cand_cnt}, ohlcv_probes={probes}, alerts={alerts_cnt}")

    # overall summary
    used = len(selected)
    print(f"[cycle] total scanned: {total_scanned} pools; OHLCV used: {used}/{ohlcv_budget}")
    
    # Rate-limit metrics
    http.update_effective_rps()
    print(
        f"[rate] req={http.get_cycle_requests()} 429={http.get_cycle_429()} "
        f"penalty={http.get_cycle_penalty():.2f}s rps?{http.get_effective_rps():.2f}"
    )
    
    # ???? ???????? ?????????
    http.log_ratelimit_health("cmc")
    if cfg.allow_gt_ohlcv_fallback:
        http.log_ratelimit_health("gt")
    
    # Health summary
    discovery_pages_done = sum(int((per_chain_stats.get(ch, {}) or {}).get("pages_done", 0)) for ch in (cfg.chains or []))
    discovery_pages_planned = sum(int((per_chain_stats.get(ch, {}) or {}).get("pages_planned", 0)) for ch in (cfg.chains or []))
    print(
        f"[health] ok={str(cycle_ok).lower()} discovery_pages={discovery_pages_done}/{discovery_pages_planned} "
        f"scanned={total_scanned} ohlcv_used={used}/{ohlcv_budget}"
    )
    if not cycle_ok and first_error:
        print(f"[health] first_error: {first_error}")
    
    return {
        "ok": cycle_ok,
        "scanned": total_scanned,
        "ohlcv_used": used,
        "ohlcv_budget": ohlcv_budget,
        "discovery_pages_done": discovery_pages_done,
        "discovery_pages_planned": discovery_pages_planned,
    }


def pick_sources(cfg: Config, cycle_idx: int) -> list[str]:
    # Deprecated rotation; always use all configured sources per cycle
    return cfg.gecko_sources_list or ["new"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run single cycle and exit")
    parser.add_argument("--health", action="store_true", help="run offline health check (config validation) and exit")
    parser.add_argument("--health-online", action="store_true", help="run online health check (mini-ping to CMC API) and exit")
    args = parser.parse_args(argv)

    cfg = Config.load()

    # Health check mode (offline: no network calls)
    if args.health:
        print("[health] Running offline health check (config validation)...")
        ok = health_check(cfg, logger=print)
        print(f"[health] Result: {'PASS' if ok else 'FAIL'}")
        import sys
        sys.exit(0 if ok else 1)
    
    # Health check online mode (with network ping)
    if args.health_online:
        http = HttpClient(cfg)
        print("[health] Running online health check (CMC API ping)...")
        # Debug: show final discovery URL with network_slug
        chain = (cfg.chains or ["ethereum"])[0]
        cmc_chain = cfg.chain_slugs.get(chain, chain) if cfg.chain_slugs else chain
        debug_url = f"{cfg.cmc_dex_base}/spot-pairs/latest?network_slug={cmc_chain}&limit=5"
        print(f"[health] debug discovery URL: {debug_url}")
        ok = health_check_online(cfg, http, logger=print)
        print(f"[health] Result: {'PASS' if ok else 'FAIL'}")
        import sys
        sys.exit(0 if ok else 1)

    cycle_idx = 0
    if args.once:
        result = run_once(cfg, cycle_idx=cycle_idx)
        return

    while True:
        cycle_idx += 1
        cycle_started = time.monotonic()
        result = run_once(cfg, cycle_idx=cycle_idx)

        elapsed = time.monotonic() - cycle_started
        sleep_for = max(0.0, cfg.loop_seconds - elapsed)
        print(f"[cycle] cycle complete, sleeping for {sleep_for:.2f}s")
        time.sleep(sleep_for)

        if cfg.max_cycles and cycle_idx >= cfg.max_cycles:
            print(f"[cycle] reached MAX_CYCLES={cfg.max_cycles}, stopping loop")
            break


if __name__ == "__main__":
    main()
