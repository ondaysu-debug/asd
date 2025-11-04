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
from .net_http import HttpClient
from .storage import Storage


def health_check(cfg: Config, logger=print) -> bool:
    """
    Offline health check: validates configuration.
    """
    ok = True
    try:
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
            logger("[health] WARN: GT_MEGAFILTER_API_KEY not set")
        else:
            logger(f"[health] gt_megafilter_api_key: ***{cfg.gt_megafilter_api_key[-4:]} - OK")
        
        if cfg.gt_megafilter_calls_per_min <= 0:
            logger("[health] FAIL: GT_MEGAFILTER_CALLS_PER_MIN must be > 0")
            ok = False
        else:
            logger(f"[health] gt_megafilter_calls_per_min: {cfg.gt_megafilter_calls_per_min} - OK")
        
        logger(f"[health] offline check: {'PASS' if ok else 'FAIL'}")
    
    except Exception as e:
        logger(f"[health] error: {type(e).__name__}: {e}")
        ok = False
    
    return ok


def health_check_online(cfg: Config, http: HttpClient, logger=print) -> bool:
    """
    Online health check: tests GT Megafilter endpoint.
    """
    ok = True
    
    try:
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
        
        logger(f"\n[health] Summary: {'PASS' if ok else 'FAIL'}")
    
    except Exception as e:
        logger(f"[health] ✗ Unhandled error: {type(e).__name__}: {e}")
        ok = False
    
    return ok


def run_minute_cycle(cfg: Config, *, cycle_idx: int) -> dict:
    """
    Упрощенный минутный цикл с единым Megafilter запросом
    """
    http = HttpClient(cfg)
    storage = Storage(cfg)
    notifier = Notifier(cfg)

    if cycle_idx == 1:
        print(f"🚀 Minute-cycle bot started. Chains: {', '.join(cfg.chains)}")
        print(f"📊 Using Megafilter for discovery + monitoring")
        print(f"⏰ Min pool age: {cfg.revival_min_age_days} days")
        print(f"🔄 Cycle duration: {cfg.loop_seconds}s")

    # Сбрасываем счетчики цикла
    http.reset_cycle_counters()

    # 1. ЕДИНЫЙ ЗАПРОС: discovery + monitoring данные
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
                except Exception as e:
                    print(f"[{chain_name}] GT discovery error: {e}")

    # 2. Логирование кандидатов
    if aggregated and cfg.save_candidates:
        now_iso = datetime.now(timezone.utc).isoformat()
        for rec in aggregated:
            out = dict(rec)
            out['ts'] = now_iso
            storage.append_jsonl(out)

    # 3. Получаем recently_seen для оптимизации
    recently_seen_by_chain: dict[str, set[str]] = {}
    with storage.get_conn() as conn:
        for chain in cfg.chains:
            recently_seen_by_chain[chain] = storage.get_recently_seen(conn, chain, cfg.seen_ttl_min)

    # 4. НЕПОСРЕДСТВЕННАЯ обработка алертов
    alerts_sent = 0
    processed_pools = 0
    skipped_seen = 0
    skipped_cooldown = 0
    
    for pool in aggregated:
        # Пропускаем recently seen
        if pool['pool'] in recently_seen_by_chain.get(pool['chain'], set()):
            skipped_seen += 1
            continue
            
        processed_pools += 1
        
        # Проверяем cooldown
        with storage.get_conn() as conn:
            last_alert = storage.get_last_alert_ts(conn, pool['pool'])
            if last_alert:
                last_dt = datetime.fromtimestamp(int(last_alert), tz=timezone.utc)
                if datetime.now(timezone.utc) - last_dt < timedelta(minutes=cfg.cooldown_min):
                    skipped_cooldown += 1
                    continue

        # Данные УЖЕ в ответе Megafilter
        vol1h = pool.get('volume_1h', 0.0)
        vol24h = pool.get('volume_24h', 0.0)
        pool_age_days = pool.get('pool_age_days', 0)
        pool_age_ok = pool_age_days >= cfg.revival_min_age_days

        # Проверяем условие алерта
        if should_alert_revival_gt(vol1h, vol24h, pool_age_ok, cfg):
            # Создаем inputs для алерта
            inputs = AlertInputs(
                chain=pool['chain'],
                pool=pool['pool'],
                url=pool.get('url', ''),
                token_symbol=pool.get('baseSymbol', ''),
                token_addr=pool.get('baseAddr', ''),
                liquidity=float(pool.get('liquidity', 0.0)),
                pool_created_at=pool.get('pool_created_at', ''),
                volume_24h=vol24h
            )
            
            # Отправляем алерт
            text = build_revival_text_gt(
                inputs,
                pool['chain'].capitalize(),
                vol1h,
                vol24h,
                "GeckoTerminal Megafilter"
            )
            notifier.send(text)
            
            # Устанавливаем cooldown
            with storage.get_conn() as conn:
                storage.set_last_alert_ts(conn, pool['pool'], int(datetime.now(timezone.utc).timestamp()))
            
            alerts_sent += 1

        # Отмечаем пул как обработанный (для seen-cache)
        with storage.get_conn() as conn:
            storage.mark_as_seen(conn, pool['chain'], pool['pool'])

    # Очистка старых seen записей
    with storage.get_conn() as conn:
        storage.purge_seen_older_than(conn, cfg.seen_ttl_sec)

    # Сводка цикла
    total_scanned = sum(int(stats.get('scanned_pairs', 0)) for stats in per_chain_stats.values())
    
    print(f"📈 [cycle {cycle_idx}] Scanned: {total_scanned}, Processed: {processed_pools}, Alerts: {alerts_sent}")
    print(f"⏭️  [cycle {cycle_idx}] Skipped: seen={skipped_seen}, cooldown={skipped_cooldown}")
    print(f"⚡ [cycle {cycle_idx}] Requests: {http.get_cycle_requests()}, 429s: {http.get_cycle_429()}")
    
    # Мониторинг здоровья rate limiters
    http.log_ratelimit_health("megafilter")

    return {
        "ok": True,
        "processed_pools": processed_pools,
        "alerts_sent": alerts_sent,
        "total_scanned": total_scanned,
        "skipped_seen": skipped_seen,
        "skipped_cooldown": skipped_cooldown,
        "requests": http.get_cycle_requests(),
        "429s": http.get_cycle_429(),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Wake-up bot with 1-minute Megafilter cycles")
    parser.add_argument("--once", action="store_true", help="run single cycle and exit")
    parser.add_argument("--health-check", action="store_true", help="run offline health check and exit")
    parser.add_argument("--health-check-online", action="store_true", help="run online health check and exit")
    args = parser.parse_args(argv)

    cfg = Config.load()

    if args.health_check:
        ok = health_check(cfg, logger=print)
        print(f"[health] Result: {'PASS' if ok else 'FAIL'}")
        import sys
        sys.exit(0 if ok else 1)
    
    if args.health_check_online:
        http = HttpClient(cfg)
        ok = health_check_online(cfg, http, logger=print)
        print(f"[health] Result: {'PASS' if ok else 'FAIL'}")
        import sys
        sys.exit(0 if ok else 1)

    cycle_idx = 0
    if args.once:
        cycle_idx = 1
        result = run_minute_cycle(cfg, cycle_idx=cycle_idx)
        return

    # Минутные циклы
    print("=" * 60)
    print("🚀 Starting 1-minute cycle bot")
    print("=" * 60)
    
    while True:
        cycle_idx += 1
        cycle_started = time.monotonic()
        
        try:
            result = run_minute_cycle(cfg, cycle_idx=cycle_idx)
        except Exception as e:
            print(f"❌ [cycle {cycle_idx}] Fatal error: {e}")
            import traceback
            traceback.print_exc()

        elapsed = time.monotonic() - cycle_started
        sleep_for = max(0.0, cfg.loop_seconds - elapsed)
        
        if sleep_for > 0:
            print(f"⏳ [cycle {cycle_idx}] Complete in {elapsed:.2f}s, sleeping {sleep_for:.2f}s\n")
            time.sleep(sleep_for)
        else:
            print(f"⚠️  [cycle {cycle_idx}] Overran by {-sleep_for:.2f}s\n")

        if cfg.max_cycles and cycle_idx >= cfg.max_cycles:
            print(f"🛑 [cycle {cycle_idx}] Reached MAX_CYCLES={cfg.max_cycles}, stopping")
            break


if __name__ == "__main__":
    main()
