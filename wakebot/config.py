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

    # APIs
    # CMC DEX (primary)
    cmc_dex_base: str
    cmc_dex_base_alt: str
    cmc_api_key: str
    # GeckoTerminal (optional fallback for OHLCV)
    gecko_base: str
    allow_gt_ohlcv_fallback: bool

    # Filters
    liquidity_min: float
    liquidity_max: float
    tx24h_max: int
    chains: List[str]

    # Limits and cache
    # CMC
    cmc_calls_per_min: int
    cmc_retry_after_cap_s: float
    # GT
    gecko_calls_per_min: int
    gecko_retry_after_cap_s: float
    gecko_ttl_sec: int

    # Discovery sources and breadth
    # CMC (primary)
    cmc_sources: str
    cmc_rotate_sources: bool
    cmc_pages_per_chain: int
    cmc_dex_pages_per_chain: int
    cmc_page_size: int
    # GT (legacy discovery; kept for tests/back-compat)
    gecko_sources: str
    gecko_rotate_sources: bool = True
    gecko_pages_per_chain: int
    gecko_dex_pages_per_chain: int = 1
    gecko_page_size: int

    # Budget for OHLCV probes (dynamic per cycle)
    max_ohlcv_probes_cap: int = 30
    cmc_safety_budget: int = 4
    gecko_safety_budget: int = 4  # legacy name (kept for back-compat)
    min_ohlcv_probes: int = 3
    # Back-compat (tests and older code may still reference this)
    max_ohlcv_probes: int

    # Loop/concurrency
    cooldown_min: int
    loop_seconds: int
    chain_scan_workers: int
    alert_fetch_workers: int
    max_cycles: int

    # Alerting and noise reduction
    alert_ratio_min: float
    min_prev24_usd: float
    revival_min_age_days: int

    # Seen-cache for OHLCV budget saving
    seen_ttl_min: int = 15
    # Back-compat (tests use seconds)
    seen_ttl_sec: int

    # Logging candidates
    save_candidates: bool
    candidates_path: Path

    # Database
    db_path: Path

    # Helper properties (populated in load())
    gecko_sources_list: List[str] | None = None
    cmc_sources_list: List[str] | None = None
    
    # Legacy revival configuration (kept for tests/back-compat)
    revival_enabled: bool = True
    revival_prev_week_max_usd: float = 3000.0
    revival_now_24h_min_usd: float = 1500.0
    revival_ratio_min: float = 2.0
    revival_use_last_hours: int = 0

    @staticmethod
    def load(env_path: str | None = None, override: bool = True) -> "Config":
        load_dotenv(dotenv_path=env_path, override=override)

        tg_bot_token = os.getenv("TG_BOT_TOKEN", "")
        tg_chat_id = os.getenv("TG_CHAT_ID", "")
        tg_parse_mode = os.getenv("TG_PARSE_MODE", "Markdown")

        # API bases
        cmc_dex_base = os.getenv("CMC_DEX_BASE", "https://api.coinmarketcap.com/dexer/v3")
        cmc_dex_base_alt = os.getenv("CMC_DEX_BASE_ALT", "https://pro-api.coinmarketcap.com/dexer/v3")
        cmc_api_key = os.getenv("CMC_API_KEY", "")
        gecko_base = os.getenv("GECKO_BASE", "https://api.geckoterminal.com/api/v2")
        allow_gt_ohlcv_fallback = _as_bool(os.getenv("ALLOW_GT_OHLCV_FALLBACK", "false"))

        # Filters
        liquidity_min = float(os.getenv("LIQUIDITY_MIN", "50000"))
        liquidity_max = float(os.getenv("LIQUIDITY_MAX", "800000"))
        tx24h_max = int(os.getenv("TX24H_MAX", "2000"))
        chains_raw = os.getenv("CHAINS", "base,solana,ethereum,bsc")
        chains = [c.strip().lower() for c in chains_raw.split(",") if c.strip()]

        # Limits/cache
        # CMC
        cmc_calls_per_min = int(os.getenv("CMC_CALLS_PER_MIN", "28"))
        cmc_retry_after_cap_s = float(os.getenv("CMC_RETRY_AFTER_CAP_S", "3.0"))
        # GT
        gecko_calls_per_min = int(os.getenv("GECKO_CALLS_PER_MIN", "28"))
        gecko_retry_after_cap_s = float(os.getenv("GECKO_RETRY_AFTER_CAP_S", "3.0"))
        gecko_ttl_sec = int(os.getenv("GECKO_TTL_SEC", "60"))

        # Sources
        # CMC
        cmc_sources = os.getenv("CMC_SOURCES", "new,trending,pools,dexes")
        cmc_rotate_sources = _as_bool(os.getenv("CMC_ROTATE_SOURCES", "true"))
        cmc_pages_per_chain = int(os.getenv("CMC_PAGES_PER_CHAIN", "2"))
        cmc_dex_pages_per_chain = int(os.getenv("CMC_DEX_PAGES_PER_CHAIN", "1"))
        cmc_page_size = int(os.getenv("CMC_PAGE_SIZE", "100"))
        # GT (legacy)
        gecko_sources = os.getenv("GECKO_SOURCES", "new,trending,pools,dexes")
        gecko_rotate_sources = _as_bool(os.getenv("GECKO_ROTATE_SOURCES", "true"))
        gecko_pages_per_chain = int(os.getenv("GECKO_PAGES_PER_CHAIN", "2"))
        gecko_dex_pages_per_chain = int(os.getenv("GECKO_DEX_PAGES_PER_CHAIN", "1"))
        gecko_page_size = int(os.getenv("GECKO_PAGE_SIZE", "100"))

        # Budget (dynamic OHLCV)
        max_ohlcv_probes_cap = int(os.getenv("MAX_OHLCV_PROBES_CAP", "30"))
        cmc_safety_budget = int(os.getenv("CMC_SAFETY_BUDGET", "4"))
        gecko_safety_budget = int(os.getenv("GECKO_SAFETY_BUDGET", str(cmc_safety_budget)))
        min_ohlcv_probes = int(os.getenv("MIN_OHLCV_PROBES", "3"))
        # Back-compat
        max_ohlcv_probes = int(os.getenv("MAX_OHLCV_PROBES", str(max_ohlcv_probes_cap)))

        # Concurrency and loop
        cooldown_min = int(os.getenv("COOLDOWN_MIN", "30"))
        loop_seconds = int(os.getenv("LOOP_SECONDS", "60"))
        chain_scan_workers = max(1, int(os.getenv("CHAIN_SCAN_WORKERS", "4")))
        alert_fetch_workers = max(1, int(os.getenv("ALERT_FETCH_WORKERS", "8")))
        max_cycles = max(0, int(os.getenv("MAX_CYCLES", "0")))

        # Alerting/noise reduction and seen-cache
        alert_ratio_min = float(os.getenv("ALERT_RATIO_MIN", "1.0"))
        min_prev24_usd = float(os.getenv("MIN_PREV24_USD", "1000"))
        revival_min_age_days = int(os.getenv("REVIVAL_MIN_AGE_DAYS", "7"))
        # Prefer minutes var; fall back to seconds
        seen_ttl_min = int(os.getenv("SEEN_TTL_MIN", "15"))
        seen_ttl_sec_env = os.getenv("SEEN_TTL_SEC")
        seen_ttl_sec = int(seen_ttl_sec_env) if seen_ttl_sec_env else int(seen_ttl_min * 60)

        # Logging
        save_candidates = _as_bool(os.getenv("SAVE_CANDIDATES", "true"))
        candidates_path = Path(os.getenv("CANDIDATES_PATH", "./candidates.jsonl")).expanduser()

        # Database
        db_path = Path(os.getenv("DB_PATH", "wake_state.sqlite")).expanduser()

        # Revival configuration
        revival_enabled = _as_bool(os.getenv("REVIVAL_ENABLED", "true"))
        revival_prev_week_max_usd = float(os.getenv("REVIVAL_PREV_WEEK_MAX_USD", "3000"))
        revival_now_24h_min_usd = float(os.getenv("REVIVAL_NOW_24H_MIN_USD", "1500"))
        revival_ratio_min = float(os.getenv("REVIVAL_RATIO_MIN", "2.0"))
        revival_use_last_hours = int(os.getenv("REVIVAL_USE_LAST_HOURS", "0"))

        cfg = Config(
            tg_bot_token=tg_bot_token,
            tg_chat_id=tg_chat_id,
            tg_parse_mode=tg_parse_mode,
            cmc_dex_base=cmc_dex_base,
            cmc_dex_base_alt=cmc_dex_base_alt,
            cmc_api_key=cmc_api_key,
            gecko_base=gecko_base,
            allow_gt_ohlcv_fallback=allow_gt_ohlcv_fallback,
            liquidity_min=liquidity_min,
            liquidity_max=liquidity_max,
            tx24h_max=tx24h_max,
            chains=chains,
            cmc_calls_per_min=cmc_calls_per_min,
            cmc_retry_after_cap_s=cmc_retry_after_cap_s,
            gecko_calls_per_min=gecko_calls_per_min,
            gecko_retry_after_cap_s=gecko_retry_after_cap_s,
            gecko_ttl_sec=gecko_ttl_sec,
            cmc_sources=cmc_sources,
            cmc_rotate_sources=cmc_rotate_sources,
            cmc_pages_per_chain=cmc_pages_per_chain,
            cmc_dex_pages_per_chain=cmc_dex_pages_per_chain,
            cmc_page_size=cmc_page_size,
            gecko_sources=gecko_sources,
            gecko_rotate_sources=gecko_rotate_sources,
            gecko_pages_per_chain=gecko_pages_per_chain,
            gecko_dex_pages_per_chain=gecko_dex_pages_per_chain,
            gecko_page_size=gecko_page_size,
            max_ohlcv_probes_cap=max_ohlcv_probes_cap,
            cmc_safety_budget=cmc_safety_budget,
            gecko_safety_budget=gecko_safety_budget,
            min_ohlcv_probes=min_ohlcv_probes,
            max_ohlcv_probes=max_ohlcv_probes,
            cooldown_min=cooldown_min,
            loop_seconds=loop_seconds,
            chain_scan_workers=chain_scan_workers,
            alert_fetch_workers=alert_fetch_workers,
            max_cycles=max_cycles,
            alert_ratio_min=alert_ratio_min,
            min_prev24_usd=min_prev24_usd,
            revival_min_age_days=revival_min_age_days,
            seen_ttl_min=seen_ttl_min,
            seen_ttl_sec=seen_ttl_sec,
            save_candidates=save_candidates,
            candidates_path=candidates_path,
            db_path=db_path,
        )

        # helper: parsed list of sources
        cfg.gecko_sources_list = [s.strip() for s in (cfg.gecko_sources or "").split(",") if s.strip()]
        cfg.cmc_sources_list = [s.strip() for s in (cfg.cmc_sources or "").split(",") if s.strip()]

        # Attach revival config
        cfg.revival_enabled = revival_enabled
        cfg.revival_prev_week_max_usd = revival_prev_week_max_usd
        cfg.revival_now_24h_min_usd = revival_now_24h_min_usd
        cfg.revival_ratio_min = revival_ratio_min
        cfg.revival_use_last_hours = revival_use_last_hours
        return cfg
