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
    pair_address: str,
    cache,  # GeckoCache instance for fallback
    pool_created_at: str | None = None,
) -> tuple[float, float, bool, str]:
    """
    Fetch 25 hourly candles from CMC DEX API v4 and return (vol1h, prev24h, ok_age, source).
    
    v4 OHLCV: /pairs/ohlcv/latest
      - network_slug=<slug>
      - contract_address=<pair_address>
      - interval=1h
      - limit=25
    
    ok_age = True if pool age > cfg.revival_min_age_days
    source = "CMC DEX" or "CMC→GT fallback" or "GeckoTerminal OHLCV"
    
    Fallback to GeckoTerminal if allow_gt_ohlcv_fallback=True and CMC fails.
    """
    key = (f"cmc25:{chain}", pair_address)
    cached = _get_cached_cmc_ohlcv(key, int(cfg.gecko_ttl_sec))
    if cached is not None:
        # Cached value includes source tag
        vol1h, prev24h, ok_age, source = cached
        return (vol1h, prev24h, ok_age, source)

    cmc_chain = _normalize_cmc_chain(cfg, chain)
    
    # CMC DEX OHLCV endpoint v4
    url = f"{cfg.cmc_dex_base}/pairs/ohlcv/latest?network_slug={cmc_chain}&contract_address={pair_address}&interval=1h&limit=25"
    
    try:
        doc = http.cmc_get_json(url, timeout=20.0) or {}
        
        # Строгая валидация структуры v4
        try:
            data = doc.get("data")
            if not isinstance(data, dict):
                raise ValueError("CMC OHLCV: data not dict")
            attrs = data.get("attributes") or {}
            candles = attrs.get("candles") or data.get("candles")
            if not isinstance(candles, list) or len(candles) < 2:
                raise ValueError("CMC OHLCV: candles missing/short")
            
            # Validate each candle format: [ts, o, h, l, c, v]
            parsed = []
            for i, c in enumerate(candles):
                if not isinstance(c, (list, tuple)) or len(c) < 6:
                    raise ValueError(f"CMC OHLCV: candle[{i}] invalid")
                try:
                    ts = int(c[0]); o = float(c[1]); h = float(c[2]); l = float(c[3]); cl = float(c[4]); v = float(c[5])
                except (TypeError, ValueError) as e:
                    raise ValueError(f"CMC OHLCV: candle[{i}] cannot convert: {e}")
                parsed.append((ts,o,h,l,cl,v))
            
            candles = parsed
        except ValueError as ve:
            print(f"[cmc][validate] {ve} for pair={pair_address}; fallback? {cfg.allow_gt_ohlcv_fallback}")
            if cfg.allow_gt_ohlcv_fallback:
                return _fallback_gt_ohlcv_25h(cfg, http, chain, pair_address, cache, pool_created_at)
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
            prev24h = sum(float(c[5]) for c in prev_window)
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
        print(f"[cmc] {chain}/{pair_address} OHLCV error: {type(e).__name__}: {e}")
        # Try fallback to GeckoTerminal
        if cfg.allow_gt_ohlcv_fallback:
            print(f"[cmc→gt] {chain}/{pair_address}: CMC exception, fallback to GT")
            return _fallback_gt_ohlcv_25h(cfg, http, chain, pair_address, cache, pool_created_at)
        val = (0.0, 0.0, False, "CMC DEX")
        _set_cached_cmc_ohlcv(key, val)
        return val


def _fallback_gt_ohlcv_25h(
    cfg: Config,
    http: HttpClient,
    chain: str,
    pair_address: str,
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
        vol1h_gt, prev24h_gt, ok_age = fetch_gt_ohlcv_25h_with_age(cfg, http, chain, pair_address, cache, pool_created_at)
        
        # Data quality logging if we have CMC data to compare
        if cmc_vol1h > 0 or cmc_prev24h > 0:
            _log_data_quality(cfg, chain, pair_address, cmc_vol1h, vol1h_gt, cmc_prev24h, prev24h_gt)
        
        return (vol1h_gt, prev24h_gt, ok_age, "CMC→GT fallback")
    except Exception as e:
        print(f"[gt] {chain}/{pair_address} fallback error: {type(e).__name__}: {e}")
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
    def pct(a, b):
        return 0.0 if b == 0 else abs(a - b) / abs(b)
    p1 = pct(vol1h_cmc, vol1h_gt)
    p2 = pct(prev24h_cmc, prev24h_gt)
    print(
        f"[dq] {chain}/{pool_id} v1h CMC={vol1h_cmc:.2f} GT={vol1h_gt:.2f} Δ={abs(vol1h_cmc-vol1h_gt):.2f} ({p1*100:.1f}%) "
        f"; prev24 CMC={prev24h_cmc:.2f} GT={prev24h_gt:.2f} Δ={abs(prev24h_cmc-prev24h_gt):.2f} ({p2*100:.1f}%)"
    )
    if max(p1, p2) > float(cfg.dq_discrepancy_threshold):
        print(f"[dq][warn] discrepancy >{cfg.dq_discrepancy_threshold*100:.0f}% for {chain}/{pool_id}")
