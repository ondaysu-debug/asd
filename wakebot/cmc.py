from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

from .config import Config
from .net_http import HttpClient


# TTL cache for CMC OHLCV 25h per (chain, pool) -> (vol1h, prev24h, ok_age)
_CMC_OHLCV_CACHE: Dict[tuple[str, str], tuple[float, tuple[float, float, bool]]] = {}
_CMC_OHLCV_LOCK = threading.Lock()


def _get_cached_cmc_ohlcv(key: tuple[str, str], ttl: int) -> tuple[float, float, bool] | None:
    now = time.time()
    with _CMC_OHLCV_LOCK:
        item = _CMC_OHLCV_CACHE.get(key)
        if not item:
            return None
        ts, data = item
        if now - ts < ttl:
            return data
        # expired
        _CMC_OHLCV_CACHE.pop(key, None)
        return None


def _set_cached_cmc_ohlcv(key: tuple[str, str], value: tuple[float, float, bool]) -> None:
    with _CMC_OHLCV_LOCK:
        _CMC_OHLCV_CACHE[key] = (time.time(), value)


def _parse_iso8601(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _normalize_cmc_chain(cfg: Config, chain: str) -> str:
    """CMC DEX uses canonical names via chain_slugs mapping"""
    s = (chain or "").strip().lower()
    # Use chain_slugs from config
    if cfg.chain_slugs and s in cfg.chain_slugs:
        return cfg.chain_slugs[s]
    # Fallback: return normalized chain
    return s


def fetch_cmc_ohlcv_25h(
    cfg: Config,
    http: HttpClient,
    chain: str,
    pool_id: str,
    cache,  # GeckoCache instance for fallback
    pool_created_at: str | None = None,
) -> tuple[float, float, bool]:
    """
    Fetch 25 hourly candles from CMC DEX API and return (vol1h, prev24h, ok_age).
    
    ok_age = True if pool age > cfg.revival_min_age_days
    
    CMC DEX endpoint (actual as of 2025): 
    GET {cmc_dex_base}/{chain}/pairs/{pool_id}/ohlcv/latest
    Params: timeframe=1h, aggregate=1, limit=25
    
    NOTE: If CMC API path differs, adjust endpoint construction below.
    Fallback to GeckoTerminal if allow_gt_ohlcv_fallback=True and CMC fails.
    """
    key = (f"cmc25:{chain}", pool_id)
    cached = _get_cached_cmc_ohlcv(key, int(cfg.gecko_ttl_sec))
    if cached is not None:
        return cached

    cmc_chain = _normalize_cmc_chain(cfg, chain)
    
    # CMC DEX OHLCV endpoint (actual as of 2025)
    # Format: /dexer/v3/{chain}/pairs/{pool_id}/ohlcv/latest
    # Params: timeframe=1h, aggregate=1, limit=25
    url = f"{cfg.cmc_dex_base}/{cmc_chain}/pairs/{pool_id}/ohlcv/latest?timeframe=1h&aggregate=1&limit=25"
    
    try:
        doc = http.cmc_get_json(url, timeout=20.0) or {}
        # CMC response structure (adjust based on actual API):
        # {"data": {"ohlcv": [[ts, o, h, l, c, v], ...]} or {"data": [candles]} }
        data_raw = doc.get("data") or {}
        
        # Try multiple possible keys for candles
        candles = (
            data_raw.get("ohlcv")
            or data_raw.get("ohlcv_list")
            or data_raw.get("candles")
            or (data_raw if isinstance(data_raw, list) else [])
        )
        
        if not candles or len(candles) < 2:
            # CMC failed, try fallback
            if cfg.allow_gt_ohlcv_fallback:
                print(f"[cmc→gt] {chain}/{pool_id}: CMC empty, fallback to GT")
                return _fallback_gt_ohlcv_25h(cfg, http, chain, pool_id, cache, pool_created_at)
            val = (0.0, 0.0, False)
            _set_cached_cmc_ohlcv(key, val)
            return val

        # Parse candles: format [ts, o, h, l, c, v]
        # vol1h = last candle volume
        try:
            vol1h = float(candles[-1][5])
        except (IndexError, TypeError, ValueError):
            vol1h = 0.0
        
        # prev24h = sum of volumes from candles[-25:-1]
        try:
            prev_window = candles[-25:-1] if len(candles) >= 25 else candles[:-1]
            prev24h = sum(float(c[5]) for c in prev_window if len(c) >= 6)
        except (IndexError, TypeError, ValueError):
            prev24h = 0.0

        # Age check: prefer pool_created_at if available
        ok_age = False
        now_dt = datetime.now(timezone.utc)
        if pool_created_at:
            created_dt = _parse_iso8601(pool_created_at)
            if created_dt is not None:
                ok_age = (now_dt - created_dt) >= timedelta(days=int(cfg.revival_min_age_days))
        
        # Fallback age check by first candle timestamp
        if not ok_age and candles:
            try:
                first_ts = int(candles[0][0])
                first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc)
                ok_age = (now_dt - first_dt) >= timedelta(days=int(cfg.revival_min_age_days))
            except (IndexError, TypeError, ValueError, OSError):
                ok_age = False

        val = (float(vol1h), float(prev24h), ok_age)
        _set_cached_cmc_ohlcv(key, val)
        return val

    except Exception as e:
        print(f"[cmc] {chain}/{pool_id} OHLCV error: {type(e).__name__}: {e}")
        # Try fallback to GeckoTerminal
        if cfg.allow_gt_ohlcv_fallback:
            print(f"[cmc→gt] {chain}/{pool_id}: CMC exception, fallback to GT")
            return _fallback_gt_ohlcv_25h(cfg, http, chain, pool_id, cache, pool_created_at)
        val = (0.0, 0.0, False)
        _set_cached_cmc_ohlcv(key, val)
        return val


def _fallback_gt_ohlcv_25h(
    cfg: Config,
    http: HttpClient,
    chain: str,
    pool_id: str,
    cache,
    pool_created_at: str | None,
) -> tuple[float, float, bool]:
    """
    Fallback to GeckoTerminal OHLCV 25h with age check.
    Returns (vol1h, prev24h, ok_age)
    """
    # Import here to avoid circular dependency
    from .gecko import fetch_gt_ohlcv_25h_with_age
    
    try:
        vol1h, prev24h, ok_age = fetch_gt_ohlcv_25h_with_age(cfg, http, chain, pool_id, cache, pool_created_at)
        return (vol1h, prev24h, ok_age)
    except Exception as e:
        print(f"[gt] {chain}/{pool_id} fallback error: {type(e).__name__}: {e}")
        return (0.0, 0.0, False)
