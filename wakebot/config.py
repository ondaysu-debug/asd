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

    # APIs (GT only)
    gecko_base: str

    # Filters
    liquidity_min: float
    liquidity_max: float
    tx24h_max: int
    chains: List[str]

    # GT limits and cache
    gecko_calls_per_min: int
    gecko_retry_after_cap_s: float
    gecko_ttl_sec: int

    # Discovery sources and breadth
    gecko_sources: str
    gecko_source_mode: str
    gecko_pages_per_chain: int
    gecko_page_size: int

    # Budget for OHLCV probes
    max_ohlcv_probes: int

    # Loop/concurrency
    cooldown_min: int
    loop_seconds: int
    chain_scan_workers: int
    alert_fetch_workers: int
    max_cycles: int

    # Logging candidates
    save_candidates: bool
    candidates_path: Path

    # Database
    db_path: Path

    # Helper properties (populated in load())
    gecko_sources_list: List[str] | None = None

    @staticmethod
    def load(env_path: str | None = None, override: bool = True) -> "Config":
        load_dotenv(dotenv_path=env_path, override=override)

        tg_bot_token = os.getenv("TG_BOT_TOKEN", "")
        tg_chat_id = os.getenv("TG_CHAT_ID", "")
        tg_parse_mode = os.getenv("TG_PARSE_MODE", "Markdown")

        gecko_base = os.getenv("GECKO_BASE", "https://api.geckoterminal.com/api/v2")

        # Filters
        liquidity_min = float(os.getenv("LIQUIDITY_MIN", "50000"))
        liquidity_max = float(os.getenv("LIQUIDITY_MAX", "800000"))
        tx24h_max = int(os.getenv("TX24H_MAX", "2000"))
        chains_raw = os.getenv("CHAINS", "base,solana,ethereum")
        chains = [c.strip().lower() for c in chains_raw.split(",") if c.strip()]

        # GT limits/cache
        gecko_calls_per_min = int(os.getenv("GECKO_CALLS_PER_MIN", "28"))
        gecko_retry_after_cap_s = float(os.getenv("GECKO_RETRY_AFTER_CAP_S", "3.0"))
        gecko_ttl_sec = int(os.getenv("GECKO_TTL_SEC", "30"))

        # Sources
        gecko_sources = os.getenv("GECKO_SOURCES", "new,trending")
        gecko_source_mode = os.getenv("GECKO_SOURCE_MODE", "rotate")
        gecko_pages_per_chain = int(os.getenv("GECKO_PAGES_PER_CHAIN", "3"))
        gecko_page_size = int(os.getenv("GECKO_PAGE_SIZE", "100"))

        # Budget
        max_ohlcv_probes = int(os.getenv("MAX_OHLCV_PROBES", "30"))

        # Concurrency and loop
        cooldown_min = int(os.getenv("COOLDOWN_MIN", "30"))
        loop_seconds = int(os.getenv("LOOP_SECONDS", "60"))
        chain_scan_workers = max(1, int(os.getenv("CHAIN_SCAN_WORKERS", "4")))
        alert_fetch_workers = max(1, int(os.getenv("ALERT_FETCH_WORKERS", "8")))
        max_cycles = max(0, int(os.getenv("MAX_CYCLES", "0")))

        # Logging
        save_candidates = _as_bool(os.getenv("SAVE_CANDIDATES", "true"))
        candidates_path = Path(os.getenv("CANDIDATES_PATH", "./candidates.jsonl")).expanduser()

        # Database
        db_path = Path(os.getenv("DB_PATH", "wake_state.sqlite")).expanduser()

        cfg = Config(
            tg_bot_token=tg_bot_token,
            tg_chat_id=tg_chat_id,
            tg_parse_mode=tg_parse_mode,
            gecko_base=gecko_base,
            liquidity_min=liquidity_min,
            liquidity_max=liquidity_max,
            tx24h_max=tx24h_max,
            chains=chains,
            gecko_calls_per_min=gecko_calls_per_min,
            gecko_retry_after_cap_s=gecko_retry_after_cap_s,
            gecko_ttl_sec=gecko_ttl_sec,
            gecko_sources=gecko_sources,
            gecko_source_mode=gecko_source_mode,
            gecko_pages_per_chain=gecko_pages_per_chain,
            gecko_page_size=gecko_page_size,
            max_ohlcv_probes=max_ohlcv_probes,
            cooldown_min=cooldown_min,
            loop_seconds=loop_seconds,
            chain_scan_workers=chain_scan_workers,
            alert_fetch_workers=alert_fetch_workers,
            max_cycles=max_cycles,
            save_candidates=save_candidates,
            candidates_path=candidates_path,
            db_path=db_path,
        )

        # helper: parsed list of sources
        cfg.gecko_sources_list = [s.strip() for s in (cfg.gecko_sources or "").split(",") if s.strip()]
        return cfg
