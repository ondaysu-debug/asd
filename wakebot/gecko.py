from __future__ import annotations

import threading
import time
from typing import Dict, Tuple

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
