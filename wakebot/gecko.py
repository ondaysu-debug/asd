from __future__ import annotations

import threading
import time
from typing import Dict, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import Config
from .net_http import HttpClient


def _normalize_gt_chain(chain: str) -> str:
    # GT uses 'eth' for Ethereum; others are unchanged
    return "eth" if chain == "ethereum" else chain


class GeckoCache:
    """
    TTL cache for GeckoTerminal OHLCV per (chain, pool) -> (vol1h, prev48h)
    """

    def __init__(self, ttl_sec: int) -> None:
        self._ttl = ttl_sec
        self._cache: Dict[tuple[str, str], tuple[float, tuple[float, float]]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> tuple[float, float] | None:
        now = time.time()
        with self._lock:
            item = self._cache.get(key)
            if not item:
                return None
            ts, data = item
            if now - ts < self._ttl:
                return data
            # expired
            self._cache.pop(key, None)
            return None

    def set(self, key: tuple[str, str], value: tuple[float, float]) -> None:
        with self._lock:
            self._cache[key] = (time.time(), value)


def fetch_ohlcv_49h(cfg: Config, http: HttpClient, chain: str, pool_id: str, cache: GeckoCache) -> tuple[float, float]:
    key = (chain, pool_id)
    cached = cache.get(key)
    if cached is not None:
        return cached

    gt_chain = _normalize_gt_chain(chain)
    url = f"{cfg.gecko_base}/networks/{gt_chain}/pools/{pool_id}/ohlcv/hour?aggregate=1&limit=49"

    try:
        doc = http.gt_get_json(url, timeout=20.0)
        attrs = ((doc or {}).get("data") or {}).get("attributes") or {}
        candles = attrs.get("ohlcv_list") or attrs.get("candles") or []
        if len(candles) < 2:
            val = (0.0, 0.0)
            cache.set(key, val)
            return val

        # candle format: [ts, o, h, l, c, v]
        vol1h = float(candles[-1][5])
        prev_window = candles[-49:-1] if len(candles) >= 49 else candles[:-1]
        prev48 = sum(float(c[-1]) for c in prev_window)

        val = (vol1h, prev48)
        cache.set(key, val)
        return val
    except Exception:
        val = (0.0, 0.0)
        cache.set(key, val)
        return val


def fetch_gt_ohlcv_25h(cfg: Config, http: HttpClient, chain: str, pool_id: str, cache: GeckoCache) -> tuple[float, float]:
    """
    Fetch 25 hourly candles from GeckoTerminal and return (vol1h, prev24h).
    Uses the same TTL cache key space but independent from 49h.
    """
    key = (f"gt25:{chain}", pool_id)
    cached = cache.get(key)
    if cached is not None:
        return cached

    gt_chain = _normalize_gt_chain(chain)
    url = f"{cfg.gecko_base}/networks/{gt_chain}/pools/{pool_id}/ohlcv/hour?aggregate=1&limit=25"

    try:
        doc = http.gt_get_json(url, timeout=20.0)
        attrs = ((doc or {}).get("data") or {}).get("attributes") or {}
        candles = attrs.get("ohlcv_list") or attrs.get("candles") or []
        if len(candles) < 2:
            val = (0.0, 0.0)
            cache.set(key, val)
            return val

        # candle format: [ts, o, h, l, c, v]
        vol1h = float(candles[-1][5])
        prev_window = candles[-25:-1] if len(candles) >= 25 else candles[:-1]
        prev24 = sum(float(c[-1]) for c in prev_window)

        val = (vol1h, prev24)
        cache.set(key, val)
        return val
    except Exception:
        val = (0.0, 0.0)
        cache.set(key, val)
        return val


def fetch_gt_ohlcv_25h_with_age(
    cfg: Config,
    http: HttpClient,
    chain: str,
    pool_id: str,
    cache: GeckoCache,
    pool_created_at: str | None = None,
) -> tuple[float, float, bool]:
    """
    Fetch 25 hourly candles from GeckoTerminal and return (vol1h, prev24h, ok_age).
    
    ok_age = True if pool age > cfg.revival_min_age_days
    Age is checked via pool_created_at if provided, otherwise by first candle timestamp.
    """
    key = (f"gt25_age:{chain}", pool_id)
    
    # Use separate cache for age-aware variant
    from .cmc import _get_cached_cmc_ohlcv, _set_cached_cmc_ohlcv
    
    cached = _get_cached_cmc_ohlcv(key, int(cfg.gecko_ttl_sec))
    if cached is not None:
        return cached

    gt_chain = _normalize_gt_chain(chain)
    url = f"{cfg.gecko_base}/networks/{gt_chain}/pools/{pool_id}/ohlcv/hour?aggregate=1&limit=25"

    now_dt = datetime.now(timezone.utc)
    try:
        doc = http.gt_get_json(url, timeout=20.0)
        attrs = ((doc or {}).get("data") or {}).get("attributes") or {}
        candles = attrs.get("ohlcv_list") or attrs.get("candles") or []
        if len(candles) < 2:
            val = (0.0, 0.0, False)
            _set_cached_cmc_ohlcv(key, val)
            return val

        # candle format: [ts, o, h, l, c, v]
        vol1h = float(candles[-1][5])
        prev_window = candles[-25:-1] if len(candles) >= 25 else candles[:-1]
        prev24 = sum(float(c[-1]) for c in prev_window)

        # Age check: prefer pool_created_at if available
        ok_age = False
        if pool_created_at:
            created_dt = _parse_iso8601(pool_created_at)
            if created_dt is not None:
                ok_age = (now_dt - created_dt) >= timedelta(days=int(cfg.revival_min_age_days))
        
        # Fallback: check first candle timestamp
        if not ok_age and candles:
            try:
                first_ts = int(candles[0][0])
                first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc)
                ok_age = (now_dt - first_dt) >= timedelta(days=int(cfg.revival_min_age_days))
            except Exception:
                ok_age = False

        val = (vol1h, prev24, ok_age)
        _set_cached_cmc_ohlcv(key, val)
        return val
    except Exception:
        val = (0.0, 0.0, False)
        _set_cached_cmc_ohlcv(key, val)
        return val


# ---------------- Revival window (24h vs previous 7d) ----------------

@dataclass(slots=True)
class RevivalWindow:
    ok_age: bool
    now_24h: float
    prev_week: float
    last_h_opt: float | None


_REVIVAL_CACHE: Dict[tuple[str, str], tuple[float, RevivalWindow]] = {}
_REVIVAL_LOCK = threading.Lock()


def _get_cached_revival(key: tuple[str, str], ttl: int) -> RevivalWindow | None:
    now = time.time()
    with _REVIVAL_LOCK:
        item = _REVIVAL_CACHE.get(key)
        if not item:
            return None
        ts, w = item
        if now - ts < ttl:
            return w
        _REVIVAL_CACHE.pop(key, None)
        return None


def _set_cached_revival(key: tuple[str, str], w: RevivalWindow) -> None:
    with _REVIVAL_LOCK:
        _REVIVAL_CACHE[key] = (time.time(), w)


def _parse_iso8601(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def fetch_revival_window(
    cfg: Config,
    http: HttpClient,
    chain: str,
    pool_id: str,
    pool_created_at: str | None,
) -> RevivalWindow:
    key = (chain, pool_id)
    cached = _get_cached_revival(key, int(cfg.gecko_ttl_sec))
    if cached is not None:
        return cached

    gt_chain = _normalize_gt_chain(chain)
    url = f"{cfg.gecko_base}/networks/{gt_chain}/pools/{pool_id}/ohlcv/hour?aggregate=1&limit=193"

    now_dt = datetime.now(timezone.utc)
    try:
        doc = http.gt_get_json(url, timeout=20.0)
        attrs = ((doc or {}).get("data") or {}).get("attributes") or {}
        candles = attrs.get("ohlcv_list") or attrs.get("candles") or []
        if not candles:
            w = RevivalWindow(ok_age=False, now_24h=0.0, prev_week=0.0, last_h_opt=None)
            _set_cached_revival(key, w)
            return w

        # candles: [ts, o, h, l, c, v]
        vols = [float(c[5]) for c in candles if isinstance(c, (list, tuple)) and len(c) >= 6]
        if not vols:
            w = RevivalWindow(ok_age=False, now_24h=0.0, prev_week=0.0, last_h_opt=None)
            _set_cached_revival(key, w)
            return w

        # Age check: prefer pool_created_at
        ok_age = False
        if pool_created_at:
            created_dt = _parse_iso8601(pool_created_at)
            if created_dt is not None:
                ok_age = (now_dt - created_dt) >= timedelta(days=int(cfg.revival_min_age_days))
        if not ok_age:
            # fallback by candles timestamps: any candle older than N days?
            try:
                oldest_ts = int(candles[0][0])
                oldest_dt = datetime.fromtimestamp(oldest_ts, tz=timezone.utc)
                ok_age = (now_dt - oldest_dt) >= timedelta(days=int(cfg.revival_min_age_days))
            except Exception:
                ok_age = False

        # Volume windows
        now_24h = sum(vols[-24:]) if len(vols) >= 1 else 0.0
        prev_week = sum(vols[-(24 + 168):-24]) if len(vols) >= (24 + 1) else 0.0
        last_h_opt = None
        if int(cfg.revival_use_last_hours) > 0:
            last_n = int(cfg.revival_use_last_hours)
            last_h_opt = sum(vols[-last_n:]) if len(vols) >= last_n else sum(vols)

        w = RevivalWindow(ok_age=ok_age, now_24h=float(now_24h), prev_week=float(prev_week), last_h_opt=None if last_h_opt is None else float(last_h_opt))
        _set_cached_revival(key, w)
        return w
    except Exception:
        w = RevivalWindow(ok_age=False, now_24h=0.0, prev_week=0.0, last_h_opt=None)
        _set_cached_revival(key, w)
        return w
