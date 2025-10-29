from __future__ import annotations

import os
import threading
import time
from typing import Tuple

import requests

# Environment-configurable settings (defaults per spec)
_CG_ONCHAIN_BASE = os.getenv("CG_ONCHAIN_BASE", "https://api.coingecko.com/api/v3").rstrip("/")
_CG_API_KEY = os.getenv("CG_API_KEY", "").strip()
_CG_TIMEOUT_SEC = float(os.getenv("CG_TIMEOUT_SEC", "20"))
_CG_TTL_SEC = float(os.getenv("CG_TTL_SEC", "60"))

# Simple in-memory TTL cache with thread lock
_cache_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, tuple[float, int, float]]] = {}


def _cache_get(key: tuple[str, str]) -> tuple[float, int, float] | None:
    now = time.time()
    with _cache_lock:
        item = _cache.get(key)
        if not item:
            return None
        ts, data = item
        if now - ts < _CG_TTL_SEC:
            return data
        _cache.pop(key, None)
        return None


def _cache_set(key: tuple[str, str], value: tuple[float, int, float]) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def fetch_onchain_pool_stats(network: str, pool_addr: str) -> tuple[float, int, float]:
    """Возвращает (vol1h_usd, tx1h_count, vol48h_usd).
    Бросает исключение при сетевой/HTTP ошибке.
    """
    key = (network, pool_addr)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    url = f"{_CG_ONCHAIN_BASE}/onchain/networks/{network}/pools/{pool_addr}"
    headers = {
        "User-Agent": "wakebot/1.0",
        "Accept": "application/json",
    }
    if _CG_API_KEY:
        headers["x-cg-pro-api-key"] = _CG_API_KEY

    r = requests.get(url, headers=headers, timeout=_CG_TIMEOUT_SEC)
    r.raise_for_status()
    try:
        doc = r.json() or {}
    except Exception:
        doc = {}

    attributes = (doc.get("data", {}).get("attributes", {}) or {})
    volume_usd = attributes.get("volume_usd") or {}
    tx = attributes.get("transactions") or {}
    tx_h1 = tx.get("h1") or {}

    vol1h = float(volume_usd.get("h1") or 0.0)
    vol48h = float(volume_usd.get("h48") or 0.0)
    if vol48h <= 0:
        h24 = float(volume_usd.get("h24") or 0.0)
        if h24 > 0:
            vol48h = h24 * 2.0
    tx1h = int((tx_h1.get("buys") or 0) + (tx_h1.get("sells") or 0))

    value: Tuple[float, int, float] = (vol1h, tx1h, vol48h)
    _cache_set(key, value)
    return value
