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
        self._cycle_penalty = 0.0
        self._cycle_429 = 0
        self._rps_effective = max(0.0, float(cfg.cmc_calls_per_min) / 60.0)

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

        # global rate limiter for CMC DEX
        cmc_base_rps = max(0.0, float(cfg.cmc_calls_per_min) / 60.0)
        cmc_min_rps = max(0.2, cmc_base_rps * 0.5)
        self._cmc_limiter = ApiRateLimiter(
            max_concurrency=10,
            adaptive=AdaptiveParams(
                base_rps=cmc_base_rps,
                min_rps=cmc_min_rps,
                backoff_threshold=0.30,
                recover_threshold=0.10,
                decrease_step=0.25,
                increase_step=0.10,
                window=60,
            ),
            log_fn=self._log,
        )
    
    def update_effective_rps(self) -> None:
        """Update effective RPS from CMC limiter"""
        try:
            self._rps_effective = self._cmc_limiter.get_rate()
        except Exception:
            pass

    # ----- Per-cycle accounting -----
    def reset_cycle_counters(self) -> None:
        self._cycle_started_at = time.monotonic()
        self._cycle_requests = 0
        self._cycle_penalty = 0.0
        self._cycle_429 = 0
        # preserve current effective RPS
    
    def reset_cycle_metrics(self) -> None:
        """Alias ??? ?????? per-cycle ?????? (req/429/penalty)"""
        self.reset_cycle_counters()

    def get_cycle_requests(self) -> int:
        return int(self._cycle_requests)

    def add_penalty(self, seconds: float = 1.0) -> None:
        """Add penalty seconds (Retry-After or backoff sleep)"""
        try:
            self._cycle_penalty += float(seconds)
        except Exception:
            self._cycle_penalty += 1.0

    def get_cycle_penalty(self) -> float:
        return float(self._cycle_penalty)
    
    def get_cycle_429(self) -> int:
        return int(self._cycle_429)
    
    def get_effective_rps(self) -> float:
        return float(self._rps_effective)

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
                self._cycle_429 += 1
                retry_after_hdr = r.headers.get("Retry-After")
                if retry_after_hdr:
                    sleep_s = _parse_retry_after(retry_after_hdr)
                    if sleep_s is not None and sleep_s > 0:
                        cap = max(0.0, self._cfg.gecko_retry_after_cap_s)
                        actual_sleep = min(sleep_s, cap)
                        self._log(f"[gt] 429 Retry-After {sleep_s:.3f}s (cap {cap:.3f}s)")
                        time.sleep(actual_sleep)
                        self.add_penalty(actual_sleep)
                else:
                    # No Retry-After header, count minimal penalty
                    self.add_penalty(0.5)
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

    # ----- CMC DEX with throttling and API key -----
    def cmc_get_json(self, url: str, timeout: float = 20.0) -> dict[str, Any]:
        # acquire limiter: may need to sleep based on tokens
        sleep_for = self._cmc_limiter.acquire()
        if sleep_for > 0:
            self._log(f"[cmc] throttling sleep {sleep_for:.3f}s @ rate={self._cmc_limiter.get_rate():.2f}")
            time.sleep(min(sleep_for, 5.0))
        try:
            session = self._session()
            # ???? ?????????? ??? ???? CMC ???????
            session.headers["X-CMC_PRO_API_KEY"] = self._cfg.cmc_api_key or ""
            
            r = session.get(url, timeout=timeout)
            status = r.status_code
            self._cmc_limiter.record_status(status)
            
            # Log short response body for 4xx errors (helps debugging)
            if 400 <= status < 500:
                try:
                    body_snippet = r.text[:600] if r.text else ""
                    self._log(f"[cmc] {status} error: {body_snippet}")
                except Exception:
                    pass

            # Respect Retry-After for 429
            if status == 429:
                self._cycle_429 += 1
                retry_after_hdr = r.headers.get("Retry-After")
                if retry_after_hdr:
                    sleep_s = _parse_retry_after(retry_after_hdr)
                    if sleep_s is not None and sleep_s > 0:
                        cap = max(0.0, self._cfg.cmc_retry_after_cap_s)
                        actual_sleep = min(sleep_s, cap)
                        self._log(f"[cmc] 429 Retry-After {sleep_s:.3f}s (cap {cap:.3f}s)")
                        time.sleep(actual_sleep)
                        self.add_penalty(actual_sleep)
                else:
                    # No Retry-After header, count minimal penalty
                    self.add_penalty(0.5)
            
            r.raise_for_status()
            try:
                return r.json() or {}
            except Exception:
                return {}
        finally:
            self._cmc_limiter.release()
            # count any finished HTTP request toward the cycle budget
            try:
                self._cycle_requests += 1
            except Exception:
                self._cycle_requests = int(self._cycle_requests) + 1
    
    # ----- Rate limiter health monitoring -----
    def log_ratelimit_health(self, prefix: str = "cmc") -> None:
        """?????? ???????? ????????? ???????? (??? ????? ????????)"""
        limiter = self._cmc_limiter if prefix.lower() == "cmc" else self._limiter
        snap = limiter.snapshot()
        self._log(
            f"[rl:{prefix}] rps={snap['effective_rps']} tokens={snap['tokens']} "
            f"p429%={snap['p429_pct']} conc={snap['concurrency']}"
        )


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
