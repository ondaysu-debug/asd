from __future__ import annotations

import email.utils
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Dict

import requests
from requests.adapters import HTTPAdapter, Retry

from .config import Config
from .rate_limit import AdaptiveParams, ApiRateLimiter

def _default_logger(msg: str) -> None:
    print(msg)

class HttpClient:
    """
    Updated HTTP client for GeckoTerminal only:
    - megafilter_get_json: для discovery через pro-api.coingecko.com
    - gt_get_json: для OHLCV через api.geckoterminal.com
    """

    def __init__(self, cfg: Config, log_fn: Callable[[str], None] | None = None) -> None:
        self._cfg = cfg
        self._log = log_fn or _default_logger
        self._local = threading.local()
        
        # Cycle accounting
        self._cycle_started_at = time.monotonic()
        self._cycle_requests = 0
        self._cycle_penalty = 0.0
        self._cycle_429 = 0

        # GT Megafilter rate limiter (pro-api.coingecko.com)
        megafilter_base_rps = max(0.1, float(cfg.gt_megafilter_calls_per_min) / 60.0)
        self._megafilter_limiter = ApiRateLimiter(
            max_concurrency=6,
            adaptive=AdaptiveParams(
                base_rps=megafilter_base_rps,
                min_rps=max(0.05, megafilter_base_rps * 0.3),
                backoff_threshold=0.25,
                recover_threshold=0.08,
                decrease_step=0.30,
                increase_step=0.10,
                window=50,
            ),
            log_fn=self._log,
        )

        # GT OHLCV rate limiter (api.geckoterminal.com)
        gecko_base_rps = max(0.1, float(cfg.gecko_calls_per_min) / 60.0)
        self._gt_limiter = ApiRateLimiter(
            max_concurrency=8,
            adaptive=AdaptiveParams(
                base_rps=gecko_base_rps,
                min_rps=max(0.05, gecko_base_rps * 0.3),
                backoff_threshold=0.20,
                recover_threshold=0.05,
                decrease_step=0.25,
                increase_step=0.08,
                window=45,
            ),
            log_fn=self._log,
        )

    # ----- GT Megafilter methods -----
    def megafilter_get_json(self, url: str, params: Optional[Dict] = None, timeout: float = 20.0) -> dict[str, Any]:
        """
        Запросы к GT Megafilter API (pro-api.coingecko.com)
        """
        sleep_for = self._megafilter_limiter.acquire()
        if sleep_for > 0:
            self._log(f"[megafilter] throttling sleep {sleep_for:.3f}s @ rate={self._megafilter_limiter.get_rate():.2f}")
            time.sleep(min(sleep_for, 5.0))
        
        try:
            session = self._session()
            # Добавляем API ключ для Megafilter
            session.headers["x-cg-pro-api-key"] = self._cfg.gt_megafilter_api_key
            
            r = session.get(url, params=params, timeout=timeout)
            status = r.status_code
            self._megafilter_limiter.record_status(status)

            # Обработка 429
            if status == 429:
                self._cycle_429 += 1
                retry_after_hdr = r.headers.get("Retry-After")
                if retry_after_hdr:
                    sleep_s = _parse_retry_after(retry_after_hdr)
                    if sleep_s is not None and sleep_s > 0:
                        cap = max(0.0, 10.0)  # cap для megafilter
                        actual_sleep = min(sleep_s, cap)
                        self._log(f"[megafilter] 429 Retry-After {sleep_s:.3f}s (cap {cap:.3f}s)")
                        time.sleep(actual_sleep)
                        self.add_penalty(actual_sleep)
                else:
                    self.add_penalty(0.5)
            
            r.raise_for_status()
            return r.json() or {}
        except Exception as e:
            self._log(f"[megafilter] API error: {e}")
            return {}
        finally:
            self._megafilter_limiter.release()
            self._cycle_requests += 1

    # ----- GT OHLCV methods -----
    def gt_get_json(self, url: str, timeout: float = 20.0) -> dict[str, Any]:
        """
        Запросы к GT OHLCV API (api.geckoterminal.com)
        """
        sleep_for = self._gt_limiter.acquire()
        if sleep_for > 0:
            self._log(f"[gt] throttling sleep {sleep_for:.3f}s @ rate={self._gt_limiter.get_rate():.2f}")
            time.sleep(min(sleep_for, 5.0))
        
        try:
            r = self._session().get(url, timeout=timeout)
            status = r.status_code
            self._gt_limiter.record_status(status)

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
                    self.add_penalty(0.5)
            
            r.raise_for_status()
            return r.json() or {}
        except Exception as e:
            self._log(f"[gt] API error: {e}")
            return {}
        finally:
            self._gt_limiter.release()
            self._cycle_requests += 1

    # ----- Session management -----
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
                status_forcelist=[500, 502, 503, 504],
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

    # ----- Cycle accounting -----
    def reset_cycle_counters(self) -> None:
        self._cycle_started_at = time.monotonic()
        self._cycle_requests = 0
        self._cycle_penalty = 0.0
        self._cycle_429 = 0

    def get_cycle_requests(self) -> int:
        return int(self._cycle_requests)

    def add_penalty(self, seconds: float = 1.0) -> None:
        try:
            self._cycle_penalty += float(seconds)
        except Exception:
            self._cycle_penalty += 1.0

    def get_cycle_penalty(self) -> float:
        return float(self._cycle_penalty)
    
    def get_cycle_429(self) -> int:
        return int(self._cycle_429)

    # ----- Rate limiter health monitoring -----
    def log_ratelimit_health(self, prefix: str = "gt") -> None:
        """Мониторинг здоровья rate limiters"""
        if prefix.lower() == "megafilter":
            limiter = self._megafilter_limiter
        else:
            limiter = self._gt_limiter
            
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
