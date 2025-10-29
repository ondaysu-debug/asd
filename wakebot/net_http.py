from __future__ import annotations

import email.utils
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import requests
from requests.adapters import HTTPAdapter, Retry

from .config import Config
from .rate_limit import AdaptiveParams, ApiRateLimiter


def _default_logger(msg: str) -> None:
    print(msg)


class HttpClient:
    """
    Shared HTTP client for GeckoTerminal with throttled JSON fetch:
    - gt_get_json: GeckoTerminal fetch with global throttling/adaptive limiter and Retry-After respect
    """

    def __init__(self, cfg: Config, log_fn: Callable[[str], None] | None = None) -> None:
        self._cfg = cfg
        self._log = log_fn or _default_logger
        self._local = threading.local()
        # per-cycle accounting
        self._cycle_started_at = time.monotonic()
        self._cycle_requests = 0
        self._cycle_penalty = 0

        # global rate limiter for GeckoTerminal (public rate ~<30/min)
        base_rps = max(0.0, float(cfg.gecko_calls_per_min) / 60.0)
        min_rps = max(0.2, base_rps * 0.5)
        self._limiter = ApiRateLimiter(
            max_concurrency=8,
            adaptive=AdaptiveParams(
                base_rps=base_rps,
                min_rps=min_rps,
                backoff_threshold=0.30,
                recover_threshold=0.10,
                decrease_step=0.25,
                increase_step=0.10,
                window=60,
            ),
            log_fn=self._log,
        )

    # ----- Per-cycle accounting -----
    def reset_cycle_counters(self) -> None:
        self._cycle_started_at = time.monotonic()
        self._cycle_requests = 0
        self._cycle_penalty = 0

    def get_cycle_requests(self) -> int:
        return int(self._cycle_requests)

    def add_penalty(self, n: int = 1) -> None:
        try:
            self._cycle_penalty += int(n)
        except Exception:
            self._cycle_penalty += 1

    def get_cycle_penalty(self) -> int:
        return int(self._cycle_penalty)

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

    # ----- GeckoTerminal with throttling -----
    def gt_get_json(self, url: str, timeout: float = 20.0) -> dict[str, Any]:
        # acquire limiter: may need to sleep based on tokens
        sleep_for = self._limiter.acquire()
        if sleep_for > 0:
            self._log(f"[gt] throttling sleep {sleep_for:.3f}s @ rate={self._limiter.get_rate():.2f}")
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
                        cap = max(0.0, self._cfg.gecko_retry_after_cap_s)
                        self._log(f"[gt] 429 Retry-After {sleep_s:.3f}s (cap {cap:.3f}s)")
                        time.sleep(min(sleep_s, cap))
                # count penalty for dynamic budget
                self.add_penalty(1)
            r.raise_for_status()
            try:
                return r.json() or {}
            except Exception:
                return {}
        finally:
            self._limiter.release()
            # count any finished HTTP request toward the cycle budget
            try:
                self._cycle_requests += 1
            except Exception:
                self._cycle_requests = int(self._cycle_requests) + 1


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
