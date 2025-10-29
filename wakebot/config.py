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
    dexscreener_base: str
    gecko_base: str

    # Discovery/filters
    market_cap_min: float
    market_cap_max: float
    tx24h_max: int
    chains: List[str]

    # Loop/concurrency
    cooldown_min: int
    loop_seconds: int
    chain_scan_workers: int
    alert_fetch_workers: int
    max_cycles: int

    # Logging candidates
    save_candidates: bool
    candidates_path: Path

    # Discovery breadth
    scan_by_dex: bool
    fallback_bucketed_search: bool
    bucket_alphabet: str
    use_two_char_buckets: bool
    max_buckets_per_chain: int
    bucket_delay_sec: float
    max_pairs_per_dex: int
    bucket_search_target: int
    bucket_search_workers: int
    bucket_retry_limit: int

    # Gecko cache
    gecko_ttl_sec: int

    # Dexscreener throttling/adaptivity
    ds_calls_per_sec_base: float
    ds_calls_per_sec_min: float
    ds_max_concurrency: int
    ds_adaptive_window: int
    ds_backoff_threshold: float
    ds_recover_threshold: float
    ds_decrease_step: float
    ds_increase_step: float
    ds_retry_after_cap_s: float

    # Database
    db_path: Path

    @staticmethod
    def load(env_path: str | None = None, override: bool = True) -> "Config":
        load_dotenv(dotenv_path=env_path, override=override)

        tg_bot_token = os.getenv("TG_BOT_TOKEN", "")
        tg_chat_id = os.getenv("TG_CHAT_ID", "")
        tg_parse_mode = os.getenv("TG_PARSE_MODE", "Markdown")

        dexscreener_base = os.getenv("DEXSCREENER_BASE", "https://api.dexscreener.com/latest/dex")
        gecko_base = os.getenv("GECKO_BASE", "https://api.geckoterminal.com/api/v2")

        market_cap_min = float(os.getenv("MARKET_CAP_MIN", "50000"))
        market_cap_max = float(os.getenv("MARKET_CAP_MAX", "800000"))
        tx24h_max = int(os.getenv("TX24H_MAX", "2000"))
        chains_raw = os.getenv("CHAINS", "base,solana,ethereum")
        chains = [c.strip().lower() for c in chains_raw.split(",") if c.strip()]

        cooldown_min = int(os.getenv("COOLDOWN_MIN", "30"))
        loop_seconds = int(os.getenv("LOOP_SECONDS", "60"))
        chain_scan_workers = max(1, int(os.getenv("CHAIN_SCAN_WORKERS", "4")))
        alert_fetch_workers = max(1, int(os.getenv("ALERT_FETCH_WORKERS", "8")))
        max_cycles = max(0, int(os.getenv("MAX_CYCLES", "0")))

        save_candidates = _as_bool(os.getenv("SAVE_CANDIDATES", "true"))
        candidates_path = Path(os.getenv("CANDIDATES_PATH", "./candidates.jsonl")).expanduser()

        scan_by_dex = _as_bool(os.getenv("SCAN_BY_DEX", "true"))
        fallback_bucketed_search = _as_bool(os.getenv("FALLBACK_BUCKETED_SEARCH", "true"))
        bucket_alphabet = os.getenv("BUCKET_ALPHABET", "abcdefghijklmnopqrstuvwxyz0123456789")
        use_two_char_buckets = _as_bool(os.getenv("USE_TWO_CHAR_BUCKETS", "true"))
        max_buckets_per_chain = int(os.getenv("MAX_BUCKETS_PER_CHAIN", "1200"))
        bucket_delay_sec = float(os.getenv("BUCKET_DELAY_SEC", "0.01"))
        max_pairs_per_dex = int(os.getenv("MAX_PAIRS_PER_DEX", "5000"))
        bucket_search_target = int(os.getenv("BUCKET_SEARCH_TARGET", "0"))
        bucket_search_workers = max(1, int(os.getenv("BUCKET_SEARCH_WORKERS", "32")))
        bucket_retry_limit = max(0, int(os.getenv("BUCKET_RETRY_LIMIT", "2")))

        gecko_ttl_sec = int(os.getenv("GECKO_TTL_SEC", "30"))

        ds_calls_per_sec_base = float(os.getenv("DS_CALLS_PER_SEC", "8"))
        ds_calls_per_sec_min = float(os.getenv("DS_CALLS_PER_SEC_MIN", "1"))
        ds_max_concurrency = int(os.getenv("DS_MAX_CONCURRENCY", "8"))
        ds_adaptive_window = int(os.getenv("DS_ADAPTIVE_WINDOW", "100"))
        ds_backoff_threshold = float(os.getenv("DS_BACKOFF_THRESHOLD", "0.30"))
        ds_recover_threshold = float(os.getenv("DS_RECOVER_THRESHOLD", "0.10"))
        ds_decrease_step = float(os.getenv("DS_DECREASE_STEP", "0.25"))
        ds_increase_step = float(os.getenv("DS_INCREASE_STEP", "0.10"))
        ds_retry_after_cap_s = float(os.getenv("DS_RETRY_AFTER_CAP_S", "3"))

        db_path = Path(os.getenv("DB_PATH", "wake_state.sqlite")).expanduser()

        return Config(
            tg_bot_token=tg_bot_token,
            tg_chat_id=tg_chat_id,
            tg_parse_mode=tg_parse_mode,
            dexscreener_base=dexscreener_base,
            gecko_base=gecko_base,
            market_cap_min=market_cap_min,
            market_cap_max=market_cap_max,
            tx24h_max=tx24h_max,
            chains=chains,
            cooldown_min=cooldown_min,
            loop_seconds=loop_seconds,
            chain_scan_workers=chain_scan_workers,
            alert_fetch_workers=alert_fetch_workers,
            max_cycles=max_cycles,
            save_candidates=save_candidates,
            candidates_path=candidates_path,
            scan_by_dex=scan_by_dex,
            fallback_bucketed_search=fallback_bucketed_search,
            bucket_alphabet=bucket_alphabet,
            use_two_char_buckets=use_two_char_buckets,
            max_buckets_per_chain=max_buckets_per_chain,
            bucket_delay_sec=bucket_delay_sec,
            max_pairs_per_dex=max_pairs_per_dex,
            bucket_search_target=bucket_search_target,
            bucket_search_workers=bucket_search_workers,
            bucket_retry_limit=bucket_retry_limit,
            gecko_ttl_sec=gecko_ttl_sec,
            ds_calls_per_sec_base=ds_calls_per_sec_base,
            ds_calls_per_sec_min=ds_calls_per_sec_min,
            ds_max_concurrency=ds_max_concurrency,
            ds_adaptive_window=ds_adaptive_window,
            ds_backoff_threshold=ds_backoff_threshold,
            ds_recover_threshold=ds_recover_threshold,
            ds_decrease_step=ds_decrease_step,
            ds_increase_step=ds_increase_step,
            ds_retry_after_cap_s=ds_retry_after_cap_s,
            db_path=db_path,
        )
