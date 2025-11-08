from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

from dotenv import load_dotenv


def _as_bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Config:
    # Telegram
    tg_bot_token: str
    tg_chat_id: str
    tg_parse_mode: str

    # QuickNode Configuration
    quicknode_rpc_url: str
    quicknode_ws_url: str
    quicknode_api_key: str
    
    # QuickNode Performance Settings
    quicknode_batch_size: int
    pool_refresh_interval_hours: int
    volume_monitoring_interval_min: int
    max_monitored_pools: int
    
    # Solana-specific settings
    solana_raydium_program_id: str
    
    # QuickNode Enhanced APIs
    use_quicknode_enhanced_apis: bool
    quicknode_dex_metrics_enabled: bool

    # GeckoTerminal Megafilter (LEGACY - сохраняем для обратной совместимости)
    gt_megafilter_base: str
    gt_megafilter_api_key: str
    gt_megafilter_calls_per_min: int
    gt_megafilter_page_size: int
    gt_megafilter_sort: str

    # Filters
    fdv_min: float
    fdv_max: float
    liquidity_min: float
    liquidity_max: float
    tx24h_max: int
    chains: List[str]
    revival_min_age_days: int  # 7 days minimum pool age

    # Loop/concurrency
    cooldown_min: int
    loop_seconds: int
    chain_scan_workers: int
    alert_fetch_workers: int
    max_cycles: int

    # Alerting and noise reduction
    alert_ratio_min: float
    min_prev24_usd: float

    # Seen-cache for OHLCV budget saving
    seen_ttl_min: int
    seen_ttl_sec: int

    # Logging candidates
    save_candidates: bool
    candidates_path: Path

    # Database
    db_path: Path

    @staticmethod
    def load(env_path: str | None = None, override: bool = True) -> "Config":
        load_dotenv(dotenv_path=env_path, override=override)

        # Telegram
        tg_bot_token = os.getenv("TG_BOT_TOKEN", "")
        tg_chat_id = os.getenv("TG_CHAT_ID", "")
        tg_parse_mode = os.getenv("TG_PARSE_MODE", "Markdown")

        # QuickNode Configuration
        quicknode_rpc_url = os.getenv("QUICKNODE_RPC_URL", "")
        quicknode_ws_url = os.getenv("QUICKNODE_WS_URL", "")
        quicknode_api_key = os.getenv("QUICKNODE_API_KEY", "")
        
        # QuickNode Performance Settings
        quicknode_batch_size = int(os.getenv("QUICKNODE_BATCH_SIZE", "100"))
        pool_refresh_interval_hours = int(os.getenv("POOL_REFRESH_INTERVAL_HOURS", "6"))
        volume_monitoring_interval_min = int(os.getenv("VOLUME_MONITORING_INTERVAL_MIN", "1"))
        max_monitored_pools = int(os.getenv("MAX_MONITORED_POOLS", "5000"))
        
        # Solana-specific settings
        solana_raydium_program_id = os.getenv("SOLANA_RAYDIUM_PROGRAM_ID", "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
        
        # QuickNode Enhanced APIs
        use_quicknode_enhanced_apis = _as_bool(os.getenv("USE_QUICKNODE_ENHANCED_APIS", "false"))
        quicknode_dex_metrics_enabled = _as_bool(os.getenv("QUICKNODE_DEX_METRICS_ENABLED", "false"))

        # GeckoTerminal Megafilter (LEGACY - сохраняем для обратной совместимости)
        gt_megafilter_base = os.getenv("GT_MEGAFILTER_BASE", "https://pro-api.coingecko.com/api/v3/onchain")
        gt_megafilter_api_key = os.getenv("GT_MEGAFILTER_API_KEY", "")
        gt_megafilter_calls_per_min = int(os.getenv("GT_MEGAFILTER_CALLS_PER_MIN", "30"))
        gt_megafilter_page_size = int(os.getenv("GT_MEGAFILTER_PAGE_SIZE", "100"))
        gt_megafilter_sort = os.getenv("GT_MEGAFILTER_SORT", "h6_trending")

        # Filters
        fdv_min = float(os.getenv("FDV_MIN", "50000"))
        fdv_max = float(os.getenv("FDV_MAX", "800000"))
        liquidity_min = float(os.getenv("LIQUIDITY_MIN", "50000"))
        liquidity_max = float(os.getenv("LIQUIDITY_MAX", "800000"))
        tx24h_max = int(os.getenv("TX24H_MAX", "2000"))
        chains_raw = os.getenv("CHAINS", "base,ethereum,solana")
        chains = [c.strip().lower() for c in chains_raw.split(",") if c.strip()]
        revival_min_age_days = int(os.getenv("REVIVAL_MIN_AGE_DAYS", "7"))  # 7 ДНЕЙ

        # Loop/concurrency
        cooldown_min = int(os.getenv("COOLDOWN_MIN", "30"))
        loop_seconds = int(os.getenv("LOOP_SECONDS", "60"))
        chain_scan_workers = max(1, int(os.getenv("CHAIN_SCAN_WORKERS", "4")))
        alert_fetch_workers = max(1, int(os.getenv("ALERT_FETCH_WORKERS", "8")))
        max_cycles = max(0, int(os.getenv("MAX_CYCLES", "0")))

        # Alerting and noise reduction
        alert_ratio_min = float(os.getenv("ALERT_RATIO_MIN", "1.0"))
        min_prev24_usd = float(os.getenv("MIN_PREV24_USD", "1000"))

        # Seen-cache
        seen_ttl_min = int(os.getenv("SEEN_TTL_MIN", "30"))
        seen_ttl_sec_env = os.getenv("SEEN_TTL_SEC")
        seen_ttl_sec = int(seen_ttl_sec_env) if seen_ttl_sec_env else int(seen_ttl_min * 60)

        # Logging
        save_candidates = _as_bool(os.getenv("SAVE_CANDIDATES", "true"))
        candidates_path = Path(os.getenv("CANDIDATES_PATH", "./candidates.jsonl")).expanduser()

        # Database
        db_path = Path(os.getenv("DB_PATH", "wake_state.sqlite")).expanduser()

        cfg = Config(
            tg_bot_token=tg_bot_token,
            tg_chat_id=tg_chat_id,
            tg_parse_mode=tg_parse_mode,
            quicknode_rpc_url=quicknode_rpc_url,
            quicknode_ws_url=quicknode_ws_url,
            quicknode_api_key=quicknode_api_key,
            quicknode_batch_size=quicknode_batch_size,
            pool_refresh_interval_hours=pool_refresh_interval_hours,
            volume_monitoring_interval_min=volume_monitoring_interval_min,
            max_monitored_pools=max_monitored_pools,
            solana_raydium_program_id=solana_raydium_program_id,
            use_quicknode_enhanced_apis=use_quicknode_enhanced_apis,
            quicknode_dex_metrics_enabled=quicknode_dex_metrics_enabled,
            gt_megafilter_base=gt_megafilter_base,
            gt_megafilter_api_key=gt_megafilter_api_key,
            gt_megafilter_calls_per_min=gt_megafilter_calls_per_min,
            gt_megafilter_page_size=gt_megafilter_page_size,
            gt_megafilter_sort=gt_megafilter_sort,
            fdv_min=fdv_min,
            fdv_max=fdv_max,
            liquidity_min=liquidity_min,
            liquidity_max=liquidity_max,
            tx24h_max=tx24h_max,
            chains=chains,
            revival_min_age_days=revival_min_age_days,
            cooldown_min=cooldown_min,
            loop_seconds=loop_seconds,
            chain_scan_workers=chain_scan_workers,
            alert_fetch_workers=alert_fetch_workers,
            max_cycles=max_cycles,
            alert_ratio_min=alert_ratio_min,
            min_prev24_usd=min_prev24_usd,
            seen_ttl_min=seen_ttl_min,
            seen_ttl_sec=seen_ttl_sec,
            save_candidates=save_candidates,
            candidates_path=candidates_path,
            db_path=db_path,
        )

        return cfg
