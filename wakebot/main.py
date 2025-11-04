from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from .alerts import (
    AlertInputs,
    Notifier,
    build_revival_text_gt,
    should_alert_revival_gt,
)
from .config import Config
from .discovery import unified_gt_discovery
from .gecko import GeckoCache
from .gt_data import GTDataService
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
        
        if not cfg.gt_megafilter_base:
            logger("[health] FAIL: GT_MEGAFILTER_BASE not configured")
            ok = False
        else:
            logger(f"[health] gt_megafilter_base: {cfg.gt_megafilter_base} - OK")
        
        if not cfg.gt_megafilter_api_key:
            logger("[health] WARN: GT_MEGAFILTER_API_KEY not set (may limit API access)")
        else:
            logger(f"[health] gt_megafilter_api_key: ***{cfg.gt_megafilter_api_key[-4:]} - OK")
        
        # 2) Check budget params
        if cfg.gt_megafilter_calls_per_min <= 0:
            logger("[health] FAIL: GT_MEGAFILTER_CALLS_PER_MIN must be > 0")
            ok = False
        else:
            logger(f"[health] gt_megafilter_calls_per_min: {cfg.gt_megafilter_calls_per_min} - OK")
        
        if cfg.gecko_calls_per_min <= 0:
            logger("[health] FAIL: GECKO_CALLS_PER_MIN must be > 0")
            ok = False
        else:
            logger(f"[health] gecko_calls_per_min: {cfg.gecko_calls_per_min} - OK")
        
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
    Enhanced online health check: tests GT Megafilter and OHLCV endpoints.
    Returns True/False and prints detailed report.
    """
    ok = True
    working_chains = []
    failed_chains = []
    
    try:
        # Test GT Megafilter endpoint
        logger("[health] Testing GT Megafilter endpoint...")
        test_url = f"{cfg.gt_megafilter_base}/pools/megafilter"
        test_params = {
            "networks": "ethereum",
            "page": 1,
            "page_size": 5,
            "fdv_usd_min": 50000,
        }
        try:
            doc = http.megafilter_get_json(test_url, params=test_params, timeout=10.0) or {}
            data = doc.get("data", [])
            if data and isinstance(data, list):
                logger(f"[health] ✓ GT Megafilter: OK - {len(data)} items")
            else:
                logger(f"[health] ⚠️  GT Megafilter: No data returned")
                ok = False
        except Exception as e:
            logger(f"[health] ✗ GT Megafilter: Exception - {type(e).__name__}: {e}")
            ok = False
        
        # Test GT OHLCV endpoint
        logger("[health] Testing GT OHLCV endpoint...")
        test_ohlcv_url = f"{cfg.gecko_base}/networks/eth/pools"
        try:
            ohlcv_doc = http.gt_get_json(test_ohlcv_url, timeout=10.0) or {}
            if ohlcv_doc.get("data"):
                logger(f"[health] ✓ GT OHLCV: OK")
            else:
                logger(f"[health] ⚠️  GT OHLCV: No data returned")
                ok = False
        except Exception as e:
            logger(f"[health] ✗ GT OHLCV: Exception - {type(e).__name__}: {e}")
            ok = False
        
        logger(f"\n[health] Summary: {'PASS' if ok else 'FAIL'}")
    
    except Exception as e:
        logger(f"[health] ✗ Unhandled error: {type(e).__name__}: {e}")
        ok = False
    
    return ok


def run_once(cfg: Config, *, cycle_idx: int) -> dict:
    """
    Обновленный цикл с GT Megafilter discovery + GT OHLCV monitoring
    """
    http = HttpClient(cfg)
    storage = Storage(cfg)
    cache = GeckoCache(cfg.gecko_ttl_sec)
    notifier = Notifier(cfg)
    gt_service = GTDataService(cfg, http, cache)

    print(f"Wake-up bot started (GeckoTerminal Megafilter). Chains: {', '.join(cfg.chains)}")
    print(f"Using Megafilter for discovery, OHLCV for monitoring")
    print(f"Minimum pool age: {cfg.revival_min_age_days} days")
    print(f"Save candidates: {cfg.save_candidates} -> {cfg.candidates_path}")
    if cfg.max_cycles:
        print(f"Max cycles: {cfg.max_cycles}")

    total_scanned = 0
    cycle_ok = True

    # Сбрасываем счетчики цикла
    http.reset_cycle_counters()

    # Discovery через GT Megafilter
    aggregated: list[dict] = []
    per_chain_stats: dict[str, dict] = {}
    
    if cfg.chains:
        max_workers = min(len(cfg.chains), cfg.chain_scan_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for chain in cfg.chains:
                futures[pool.submit(unified_gt_discovery, cfg, http, storage, chain, cycle_idx)] = chain
            
            for fut in as_completed(futures):
                chain_name = futures[fut]
                try:
                    items, stats = fut.result()
                    aggregated.extend(items or [])
                    per_chain_stats[chain_name] = stats or {}
                    total_scanned += int((stats or {}).get('scanned_pairs', 0))
                except Exception as e:
                    print(f"[{chain_name}] GT discovery error: {e}")
                    cycle_ok = False

    # Log candidates в JSONL если включено
    if aggregated and cfg.save_candidates:
        now_iso = datetime.now(timezone.utc).isoformat()
        for rec in aggregated:
            out = dict(rec)
            out['ts'] = now_iso
            storage.append_jsonl(out)

    # Compute dynamic budget для OHLCV probes (GT only now)
    total_budget = int(cfg.gecko_calls_per_min * (cfg.loop_seconds / 60.0))
    discovery_cost = sum(int((per_chain_stats.get(ch, {}) or {}).get('pages_planned', 0)) for ch in (cfg.chains or []))
    spent_so_far = int(http.get_cycle_requests() + http.get_cycle_penalty())
    
    available_for_ohlcv = max(0, total_budget - discovery_cost - int(cfg.gecko_safety_budget))
    ohlcv_budget = int(min(available_for_ohlcv, cfg.max_ohlcv_probes_cap))
    if available_for_ohlcv > 0:
        ohlcv_budget = int(max(cfg.min_ohlcv_probes, ohlcv_budget))
    else:
        ohlcv_budget = 0
        
    print(f"[budget] total={total_budget}, discovery_cost={discovery_cost}, spent={spent_so_far}, "
          f"avail_ohlcv={available_for_ohlcv}, final_ohlcv_budget={ohlcv_budget}")

    # Seen-cache per chain чтобы избежать траты бюджета на недавно проверенные пулы
    recently_seen_by_chain: dict[str, set[str]] = {}
    with storage.get_conn() as conn:
        for chain in cfg.chains:
            recently_seen_by_chain[chain] = storage.get_recently_seen(conn, chain, cfg.seen_ttl_min)
    
    candidates = [m for m in aggregated if m.get('pool') not in recently_seen_by_chain.get(m.get('chain'), set())]
    skipped_seen = max(0, len(aggregated) - len(candidates))

    # Сортировка и ограничение OHLCV probes по ликвидности и транзакциям
    if candidates:
        candidates.sort(
            key=lambda m: (
                float(m.get('liquidity', 0.0)),
                int(m.get('tx24h', 0)),
            ),
            reverse=True,
        )
    
    selected = candidates[:ohlcv_budget] if ohlcv_budget > 0 else []

    # Распределение выбранных кандидатов по сетям для логирования
    per_chain_selection: dict[str, int] = {}
    for m in selected:
        ch = m.get('chain')
        per_chain_selection[ch] = per_chain_selection.get(ch, 0) + 1

    # Параллельный fetch + алерты
    if selected:
        workers = max(1, min(len(selected), cfg.alert_fetch_workers))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            probed_total = 0
            probed_ok = 0
            alerts_by_chain: dict[str, int] = {}
            
            for meta in selected:
                inputs = AlertInputs(
                    chain=meta['chain'],
                    pool=meta['pool'],
                    url=meta.get('url', ''),
                    token_symbol=meta.get('baseSymbol', ''),
                    token_addr=meta.get('baseAddr', ''),
                    liquidity=float(meta.get('liquidity', 0.0)),
                    pool_created_at=str(meta.get('pool_created_at', '')),
                    volume_24h=float(meta.get('volume_24h', 0.0))
                )
                
                def _work(inp: AlertInputs):
                    # Cooldown проверка
                    with storage.get_conn() as conn:
                        last = storage.get_last_alert_ts(conn, inp.pool)
                        if last:
                            last_dt = datetime.fromtimestamp(int(last), tz=timezone.utc)
                            if datetime.now(timezone.utc) - last_dt < timedelta(minutes=cfg.cooldown_min):
                                return {"probed": True, "probed_ok": True, "alert": False, "chain": inp.chain, "source": "GT"}

                    # Используем GT DATA SERVICE
                    vol1h, vol24h, ok_age, source = gt_service.fetch_volume_metrics(inp.chain, inp.pool, inp.pool_created_at)
                    
                    # Отмечаем как проверенные независимо от результата алерта
                    with storage.get_conn() as conn:
                        storage.mark_as_seen(conn, inp.chain, inp.pool)

                    # Используем GT функцию проверки
                    if not should_alert_revival_gt(vol1h, vol24h, ok_age, cfg):
                        return {"probed": True, "probed_ok": True, "alert": False, "chain": inp.chain, "source": source}
                    
                    # Отправляем алерт и устанавливаем cooldown
                    text = build_revival_text_gt(inp, inp.chain.capitalize(), vol1h, vol24h, source)
                    notifier.send(text)
                    
                    with storage.get_conn() as conn:
                        storage.set_last_alert_ts(conn, inp.pool, int(datetime.now(timezone.utc).timestamp()))
                    
                    return {"probed": True, "probed_ok": True, "alert": True, "chain": inp.chain, "source": source}

                futures[pool.submit(_work, inputs)] = inputs.pool
            
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    probed_total += 1
                    if isinstance(res, dict) and res.get('probed_ok'):
                        probed_ok += 1
                        if res.get('alert'):
                            ch = res.get('chain') or '?'
                            alerts_by_chain[ch] = alerts_by_chain.get(ch, 0) + 1
                except Exception as e:
                    pid = futures[fut]
                    print(f"[alert] {pid} error: {e}")
    else:
        probed_total = 0
        probed_ok = 0
        alerts_by_chain = {}

    # Очистка старых seen записей
    with storage.get_conn() as conn:
        storage.purge_seen_older_than(conn, cfg.seen_ttl_sec)

    # Сводка по сетям
    for chain in cfg.chains:
        scanned_cnt = int((per_chain_stats.get(chain, {}) or {}).get('scanned_pairs', 0))
        cand_cnt = len([m for m in candidates if m.get('chain') == chain])
        probes = int(per_chain_selection.get(chain, 0))
        alerts_cnt = int(alerts_by_chain.get(chain, 0))
        print(f"[cycle] {chain}: scanned={scanned_cnt}, candidates={cand_cnt}, ohlcv_probes={probes}, alerts={alerts_cnt}")

    # Общая сводка
    used = len(selected)
    print(f"[cycle] total scanned: {total_scanned} pools; OHLCV used: {used}/{ohlcv_budget}")
    
    # Метрики rate limit
    print(f"[rate] req={http.get_cycle_requests()} 429={http.get_cycle_429()} "
          f"penalty={http.get_cycle_penalty():.2f}s")
    
    # Мониторинг здоровья rate limiters
    http.log_ratelimit_health("megafilter")
    http.log_ratelimit_health("gt")
    
    # Сводка здоровья
    discovery_pages_done = sum(int((per_chain_stats.get(ch, {}) or {}).get('pages_done', 0)) for ch in (cfg.chains or []))
    discovery_pages_planned = sum(int((per_chain_stats.get(ch, {}) or {}).get('pages_planned', 0)) for ch in (cfg.chains or []))
    
    print(f"[health] ok={str(cycle_ok).lower()} discovery_pages={discovery_pages_done}/{discovery_pages_planned} "
          f"scanned={total_scanned} ohlcv_used={used}/{ohlcv_budget}")
    
    return {
        "ok": cycle_ok,
        "scanned": total_scanned,
        "ohlcv_used": used,
        "ohlcv_budget": ohlcv_budget,
        "discovery_pages_done": discovery_pages_done,
        "discovery_pages_planned": discovery_pages_planned,
    }


def main(args_list: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Wake-up bot with GeckoTerminal Megafilter")
    parser.add_argument("--health-check", action="store_true", help="Run offline health check only")
    parser.add_argument("--health-check-online", action="store_true", help="Run online health check only")
    parser.add_argument("--env", type=str, default=None, help="Path to .env file")
    args = parser.parse_args(args_list)

    cfg = Config.load(env_path=args.env, override=True)

    if args.health_check:
        ok = health_check(cfg, logger=print)
        exit(0 if ok else 1)
    
    if args.health_check_online:
        http = HttpClient(cfg)
        ok = health_check_online(cfg, http, logger=print)
        exit(0 if ok else 1)

    # Main loop
    cycle_idx = 1
    while True:
        print(f"\n{'=' * 60}\nCycle {cycle_idx}\n{'=' * 60}")
        cycle_start = time.monotonic()
        
        try:
            stats = run_once(cfg, cycle_idx=cycle_idx)
            if not stats.get("ok", True):
                print("[cycle] Some issues detected, but continuing...")
        except Exception as e:
            print(f"[cycle] Fatal error: {e}")
            import traceback
            traceback.print_exc()
        
        cycle_elapsed = time.monotonic() - cycle_start
        print(f"[cycle] elapsed: {cycle_elapsed:.1f}s")
        
        # Check if we've reached max_cycles
        if cfg.max_cycles > 0 and cycle_idx >= cfg.max_cycles:
            print(f"[cycle] Reached max cycles ({cfg.max_cycles}), exiting...")
            break
        
        # Sleep until next cycle
        if cycle_elapsed < cfg.loop_seconds:
            sleep_time = cfg.loop_seconds - cycle_elapsed
            print(f"[cycle] sleeping for {sleep_time:.1f}s until next cycle...")
            time.sleep(sleep_time)
        else:
            print(f"[cycle] Cycle took longer than loop_seconds ({cfg.loop_seconds}s), starting next cycle immediately")
        
        cycle_idx += 1
