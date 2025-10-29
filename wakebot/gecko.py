from __future__ import annotations

import threading
import time
from typing import Dict, Tuple

from .config import Config
from .http import HttpClient


class GeckoCache:
    """
    TTL cache for GeckoTerminal per (chain, pool) -> (vol1h, tx1h, vol48h)
    """

    def __init__(self, ttl_sec: int) -> None:
        self._ttl = ttl_sec
        self._cache: Dict[tuple[str, str], tuple[float, tuple[float, int, float]]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> tuple[float, int, float] | None:
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

    def set(self, key: tuple[str, str], value: tuple[float, int, float]) -> None:
        with self._lock:
            self._cache[key] = (time.time(), value)


def fetch_gecko_metrics(cfg: Config, http: HttpClient, chain: str, pool_addr: str, cache: GeckoCache) -> tuple[float, int, float]:
    key = (chain, pool_addr)
    cached = cache.get(key)
    if cached is not None:
        return cached

    gecko_chain = "ethereum" if chain == "ethereum" else chain
    url = f"{cfg.gecko_base}/networks/{gecko_chain}/pools/{pool_addr}"
    try:
        doc = http.get_json(url, timeout=20.0)
        attributes = (doc.get("data", {}).get("attributes", {}) or {})
        volume_usd = attributes.get("volume_usd") or {}
        tx = attributes.get("transactions") or {}
        tx_h1 = tx.get("h1") or {}
        vol1h = float(volume_usd.get("h1") or 0.0)
        vol48h = float(volume_usd.get("h48") or volume_usd.get("d2") or 0.0)
        if vol48h <= 0:
            vol48h = float(volume_usd.get("h24") or 0.0) * 2.0
        tx1h = int((tx_h1.get("buys") or 0) + (tx_h1.get("sells") or 0))
        value = (vol1h, tx1h, vol48h)
    except Exception:
        value = (0.0, 0, 0.0)

    cache.set(key, value)
    return value
