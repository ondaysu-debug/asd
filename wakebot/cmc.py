from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

from .config import Config
from .net_http import HttpClient


# TTL cache for CMC OHLCV 25h per (chain, pool) -> (vol1h, prev24h, ok_age, source)
_CMC_OHLCV_CACHE: Dict[tuple[str, str], tuple[float, tuple[float, float, bool, str]]] = {}
_CMC_OHLCV_LOCK = threading.Lock()


def _get_cached_cmc_ohlcv(key: tuple[str, str], ttl: int) -> tuple[float, float, bool, str] | None:
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


def _set_cached_cmc_ohlcv(key: tuple[str, str], value: tuple[float, float, bool, str]) -> None:
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


def _validate_cmc_ohlcv_doc(doc: dict, pool_id: str = "") -> list:
    """
    Strict validation of CMC OHLCV response structure.
    Expected: {"data": {"attributes": {"candles": [[ts,o,h,l,c,v], ...]}}}
    
    Returns parsed candles array or raises ValueError on validation failure.
    """
    if not isinstance(doc, dict):
        raise ValueError("CMC OHLCV: response not a dict")
    
    data_raw = doc.get("data")
    if not isinstance(data_raw, dict):
        raise ValueError("CMC OHLCV: missing or invalid 'data' field")
    
    # Check for attributes
    attrs = data_raw.get("attributes")
    if not isinstance(attrs, dict):
        raise ValueError("CMC OHLCV: missing 'data.attributes'")
    
    # Try multiple possible keys for candles
    candles = attrs.get("candles") or attrs.get("ohlcv_list") or attrs.get("ohlcv")
    
    # Fallback: check direct data keys
    if candles is None:
        candles = data_raw.get("ohlcv") or data_raw.get("ohlcv_list") or data_raw.get("candles")
    
    if not isinstance(candles, list):
        raise ValueError("CMC OHLCV: missing 'candles/ohlcv_list' or not a list")
    
    # Validate each candle structure: [ts, o, h, l, c, v]
    for i, c in enumerate(candles):
        if not isinstance(c, (list, tuple)):
            raise ValueError(f"CMC OHLCV: candle[{i}] not a list/tuple")
        if len(c) < 6:
            raise ValueError(f"CMC OHLCV: candle[{i}] has {len(c)} elements, expected >= 6")
        # Validate and convert OHLCV values to float [o,h,l,c,v at indices 1-5]
        for j in range(1, 6):
            try:
                float(c[j])
            except (TypeError, ValueError) as e:
                raise ValueError(f"CMC OHLCV: candle[{i}][{j}] cannot convert to float: {e}")
    
    return candles


def fetch_cmc_ohlcv_25h(
    cfg: Config,
    http: HttpClient,
    chain: str,
    pool_id: str,
    cache,  # GeckoCache instance for fallback
    pool_created_at: str | None = None,
) -> tuple[float, float, bool, str]:
    """
    Fetch 25 hourly candles from CMC DEX API and return (vol1h, prev24h, ok_age, source).
    
    ok_age = True if pool age > cfg.revival_min_age_days
    source = "CMC DEX" or "CMC→GT fallback" or "GeckoTerminal OHLCV"
    
    CMC DEX endpoint (actual as of 2025): 
    GET {cmc_dex_base}/{chain}/pairs/{pool_id}/ohlcv/latest
    Params: timeframe=1h, aggregate=1, limit=25
    
    NOTE: If CMC API path differs, adjust endpoint construction below.
    Fallback to GeckoTerminal if allow_gt_ohlcv_fallback=True and CMC fails.
    """
    key = (f"cmc25:{chain}", pool_id)
    cached = _get_cached_cmc_ohlcv(key, int(cfg.gecko_ttl_sec))
    if cached is not None:
        # Cached value includes source tag
        vol1h, prev24h, ok_age, source = cached
        return (vol1h, prev24h, ok_age, source)

    cmc_chain = _normalize_cmc_chain(cfg, chain)
    
    # CMC DEX OHLCV endpoint v4 (actual as of 2025)
    # Format: /v4/dex/pairs/ohlcv/latest
    # Params: chain_slug={chain}, pair_address={pool_id}, timeframe=1h, aggregate=1, limit=25
    url = f"{cfg.cmc_dex_base}/pairs/ohlcv/latest?chain_slug={cmc_chain}&pair_address={pool_id}&timeframe=1h&aggregate=1&limit=25"
    
    try:
        doc = http.cmc_get_json(url, timeout=20.0) or {}
        
        # Strict validation: will raise ValueError on failure
        try:
            candles = _validate_cmc_ohlcv_doc(doc, pool_id)
        except ValueError as ve:
            print(f"[cmc][validate] {ve} for pair={pool_id}; fallback? {cfg.allow_gt_ohlcv_fallback}")
            if cfg.allow_gt_ohlcv_fallback:
                return _fallback_gt_ohlcv_25h(cfg, http, chain, pool_id, cache, pool_created_at)
            val = (0.0, 0.0, False, "CMC DEX")
            _set_cached_cmc_ohlcv(key, val)
            return val
        
        if not candles or len(candles) < 2:
            # CMC failed, try fallback
            if cfg.allow_gt_ohlcv_fallback:
                print(f"[cmc→gt] {chain}/{pool_id}: CMC empty, fallback to GT")
                return _fallback_gt_ohlcv_25h(cfg, http, chain, pool_id, cache, pool_created_at)
            val = (0.0, 0.0, False, "CMC DEX")
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

        val = (float(vol1h), float(prev24h), ok_age, "CMC DEX")
        _set_cached_cmc_ohlcv(key, val)
        return val

    except Exception as e:
        print(f"[cmc] {chain}/{pool_id} OHLCV error: {type(e).__name__}: {e}")
        # Try fallback to GeckoTerminal
        if cfg.allow_gt_ohlcv_fallback:
            print(f"[cmc→gt] {chain}/{pool_id}: CMC exception, fallback to GT")
            return _fallback_gt_ohlcv_25h(cfg, http, chain, pool_id, cache, pool_created_at)
        val = (0.0, 0.0, False, "CMC DEX")
        _set_cached_cmc_ohlcv(key, val)
        return val


def _fallback_gt_ohlcv_25h(
    cfg: Config,
    http: HttpClient,
    chain: str,
    pool_id: str,
    cache,
    pool_created_at: str | None,
    cmc_vol1h: float = 0.0,
    cmc_prev24h: float = 0.0,
) -> tuple[float, float, bool, str]:
    """
    Fallback to GeckoTerminal OHLCV 25h with age check.
    Returns (vol1h, prev24h, ok_age, source)
    
    If cmc_vol1h/cmc_prev24h provided, log data quality comparison.
    """
    # Import here to avoid circular dependency
    from .gecko import fetch_gt_ohlcv_25h_with_age
    
    try:
        vol1h_gt, prev24h_gt, ok_age = fetch_gt_ohlcv_25h_with_age(cfg, http, chain, pool_id, cache, pool_created_at)
        
        # Data quality logging if we have CMC data to compare
        if cmc_vol1h > 0 or cmc_prev24h > 0:
            _log_data_quality(cfg, chain, pool_id, cmc_vol1h, vol1h_gt, cmc_prev24h, prev24h_gt)
        
        return (vol1h_gt, prev24h_gt, ok_age, "CMC→GT fallback")
    except Exception as e:
        print(f"[gt] {chain}/{pool_id} fallback error: {type(e).__name__}: {e}")
        return (0.0, 0.0, False, "GeckoTerminal OHLCV")


def _log_data_quality(
    cfg: Config,
    chain: str,
    pool_id: str,
    vol1h_cmc: float,
    vol1h_gt: float,
    prev24h_cmc: float,
    prev24h_gt: float,
) -> None:
    """Log data quality comparison between CMC and GT"""
    try:
        threshold = float(cfg.dq_discrepancy_threshold)
        # Calculate absolute and relative differences
        dv1 = abs(vol1h_cmc - vol1h_gt)
        dv1_rel = dv1 / max(1.0, vol1h_cmc) if vol1h_cmc > 0 else 0.0
        
        dprev = abs(prev24h_cmc - prev24h_gt)
        dprev_rel = dprev / max(1.0, prev24h_cmc) if prev24h_cmc > 0 else 0.0
        
        # Log comparison
        print(
            f"[dq] {chain}/{pool_id} v1h CMC={vol1h_cmc:.2f} GT={vol1h_gt:.2f} Δ={dv1:.2f} ({dv1_rel:.1%}); "
            f"prev24 CMC={prev24h_cmc:.2f} GT={prev24h_gt:.2f} Δ={dprev:.2f} ({dprev_rel:.1%})"
        )
        
        # Warning if discrepancy exceeds threshold
        if dv1_rel > threshold or dprev_rel > threshold:
            print(f"[dq][warn] ⚠️  discrepancy >{int(threshold*100)}% for {chain}/{pool_id}")
    except Exception as e:
        print(f"[dq] error logging quality for {chain}/{pool_id}: {e}")
