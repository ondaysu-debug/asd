from __future__ import annotations

import email.utils
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import requests
from requests.adapters import HTTPAdapter, Retry

from .config import Config
from .rate_limit import AdaptiveParams, DexscreenerLimiter


def _default_logger(msg: str) -> None:
    print(msg)


class HttpClient:
    """
    Shared HTTP client with two helpers:
    - get_json: generic JSON fetch (used for Gecko)
    - ds_get_json: Dexscreener fetch with global throttling/adaptive limiter and Retry-After respect
    """

    def __init__(self, cfg: Config, log_fn: Callable[[str], None] | None = None) -> None:
        self._cfg = cfg
        self._log = log_fn or _default_logger
        self._local = threading.local()

        # global rate limiter for Dexscreener
        self._limiter = DexscreenerLimiter(
            max_concurrency=cfg.ds_max_concurrency,
            adaptive=AdaptiveParams(
                base_rps=cfg.ds_calls_per_sec_base,
                min_rps=cfg.ds_calls_per_sec_min,
                backoff_threshold=cfg.ds_backoff_threshold,
                recover_threshold=cfg.ds_recover_threshold,
                decrease_step=cfg.ds_decrease_step,
                increase_step=cfg.ds_increase_step,
                window=cfg.ds_adaptive_window,
            ),
            log_fn=self._log,
        )

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "wakebot/1.0",
            "Accept": "application/json",
        })
        adapter = HTTPAdapter(
            pool_connections=128,
            pool_maxsize=128,
            max_retries=Retry(
                total=2,
                backoff_factor=0.4,
                status_forcelist=[500, 502, 503, 504],  # leave 429 to limiter handling
                allowed_methods=frozenset(["GET"]),
            ),
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._build_session()
            self._local.session = session
        return session

    # ----- generic -----
    def get_json(self, url: str, timeout: float = 20.0) -> dict[str, Any]:
        r = self._session().get(url, timeout=timeout)
        r.raise_for_status()
        try:
            return r.json() or {}
        except Exception:
            return {}

    # ----- Dexscreener with throttling -----
    def ds_get_json(self, url: str, timeout: float = 20.0) -> dict[str, Any]:
        # acquire limiter: may need to sleep based on tokens
        sleep_for = self._limiter.acquire()
        if sleep_for > 0:
            self._log(f"[ds] throttling sleep {sleep_for:.3f}s @ rate={self._limiter.get_rate():.2f}")
            time.sleep(min(sleep_for, 5.0))
        try:
            r = self._session().get(url, timeout=timeout)
            status = r.status_code
            self._limiter.record_status(status)

            # Respect Retry-After
            if status == 429:
                retry_after_hdr = r.headers.get("Retry-After")
                if retry_after_hdr:
                    sleep_s = _parse_retry_after(retry_after_hdr)
                    if sleep_s is not None and sleep_s > 0:
                        cap = max(0.0, self._cfg.ds_retry_after_cap_s)
                        self._log(f"[ds] 429 Retry-After {sleep_s:.3f}s (cap {cap:.3f}s)")
                        time.sleep(min(sleep_s, cap))
            r.raise_for_status()
            try:
                return r.json() or {}
            except Exception:
                return {}
        finally:
            self._limiter.release()


def _parse_retry_after(value: str) -> Optional[float]:
    # Either seconds or HTTP-date
    value = value.strip()
    try:
        sec = float(value)
        # simple seconds value
        return max(0.0, sec)
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (dt - now).total_seconds()
        return max(0.0, delta)
    except Exception:
        return None
