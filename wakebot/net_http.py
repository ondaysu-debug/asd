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
    Упрощенный HTTP client для GeckoTerminal Megafilter только
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

        # ТОЛЬКО Megafilter rate limiter (один источник данных)
        megafilter_base_rps = max(0.1, float(cfg.gt_megafilter_calls_per_min) / 60.0)
        self._megafilter_limiter = ApiRateLimiter(
            max_concurrency=4,  # уменьшено для 1-минутных циклов
            adaptive=AdaptiveParams(
                base_rps=megafilter_base_rps,
                min_rps=max(0.05, megafilter_base_rps * 0.3),
                backoff_threshold=0.25,
                recover_threshold=0.08,
                decrease_step=0.30,
                increase_step=0.10,
                window=30,  # уменьшено окно для минутных циклов
            ),
            log_fn=self._log,
        )
        
        # QuickNode rate limiter
        self._quicknode_limiter = ApiRateLimiter(
            max_concurrency=8,  # QuickNode обычно позволяет больше
            adaptive=AdaptiveParams(
                base_rps=10.0,  # QuickNode обычно позволяет больше RPS
                min_rps=1.0,
                backoff_threshold=0.1,
                recover_threshold=0.02,
                decrease_step=0.50,
                increase_step=0.10,
                window=30,
            ),
            log_fn=self._log,
        )

    # ----- GT Megafilter methods -----
    def megafilter_get_json(self, url: str, params: Optional[Dict] = None, timeout: float = 20.0) -> dict[str, Any]:
        """
        Запросы к GT Megafilter API (единый источник данных)
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

    # ----- QuickNode methods -----
    def quicknode_solana_rpc(self, payload: Dict, timeout: float = 30.0) -> dict[str, Any]:
        """
        QuickNode Solana JSON-RPC вызовы
        """
        sleep_for = self._quicknode_limiter.acquire()
        if sleep_for > 0:
            self._log(f"[quicknode/solana] throttling sleep {sleep_for:.3f}s")
            time.sleep(min(sleep_for, 5.0))
        
        try:
            session = self._session()
            url = self._cfg.quicknode_rpc_url
            
            headers = {
                "Content-Type": "application/json",
            }
            
            # QuickNode может использовать API key в headers или URL
            if self._cfg.quicknode_api_key:
                headers["Authorization"] = f"Bearer {self._cfg.quicknode_api_key}"
            
            r = session.post(url, json=payload, headers=headers, timeout=timeout)
            status = r.status_code
            self._quicknode_limiter.record_status(status)

            if status == 429:
                self._handle_rate_limit(r)
            
            r.raise_for_status()
            return r.json() or {}
            
        except Exception as e:
            self._log(f"[quicknode/solana] RPC error: {e}")
            return {}
        finally:
            self._quicknode_limiter.release()
            self._cycle_requests += 1
    
    def quicknode_evm_rpc(self, network: str, payload: Dict, timeout: float = 30.0) -> dict[str, Any]:
        """
        QuickNode EVM JSON-RPC вызовы для конкретной сети
        """
        sleep_for = self._quicknode_limiter.acquire()
        if sleep_for > 0:
            self._log(f"[quicknode/{network}] throttling sleep {sleep_for:.3f}s")
            time.sleep(min(sleep_for, 5.0))
        
        try:
            session = self._session()
            # QuickNode предоставляет отдельные endpoints для разных сетей
            # Пользователь должен настроить правильный URL в конфигурации
            url = self._cfg.quicknode_rpc_url
            
            headers = {
                "Content-Type": "application/json",
            }
            
            if self._cfg.quicknode_api_key:
                headers["Authorization"] = f"Bearer {self._cfg.quicknode_api_key}"
            
            r = session.post(url, json=payload, headers=headers, timeout=timeout)
            status = r.status_code
            self._quicknode_limiter.record_status(status)

            if status == 429:
                self._handle_rate_limit(r)
            
            r.raise_for_status()
            return r.json() or {}
            
        except Exception as e:
            self._log(f"[quicknode/{network}] RPC error: {e}")
            return {}
        finally:
            self._quicknode_limiter.release()
            self._cycle_requests += 1
    
    def quicknode_batch_rpc(self, requests: List[Dict], timeout: float = 60.0) -> list[dict]:
        """
        Batch RPC запросы к QuickNode
        """
        sleep_for = self._quicknode_limiter.acquire()
        if sleep_for > 0:
            self._log(f"[quicknode/batch] throttling sleep {sleep_for:.3f}s")
            time.sleep(min(sleep_for, 5.0))
        
        try:
            session = self._session()
            url = self._cfg.quicknode_rpc_url
            
            headers = {
                "Content-Type": "application/json",
            }
            
            if self._cfg.quicknode_api_key:
                headers["Authorization"] = f"Bearer {self._cfg.quicknode_api_key}"
            
            # Batch запрос - массив RPC запросов
            r = session.post(url, json=requests, headers=headers, timeout=timeout)
            status = r.status_code
            self._quicknode_limiter.record_status(status)

            if status == 429:
                self._handle_rate_limit(r)
            
            r.raise_for_status()
            response = r.json()
            
            # Batch response - массив RPC responses
            return response if isinstance(response, list) else []
            
        except Exception as e:
            self._log(f"[quicknode/batch] RPC error: {e}")
            return []
        finally:
            self._quicknode_limiter.release()
            self._cycle_requests += len(requests)  # Учитываем все запросы в батче
    
    def _handle_rate_limit(self, response):
        """Обработка rate limiting от QuickNode"""
        self._cycle_429 += 1
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            sleep_s = _parse_retry_after(retry_after)
            if sleep_s and sleep_s > 0:
                actual_sleep = min(sleep_s, 30.0)
                self._log(f"[quicknode] 429 Retry-After {sleep_s:.3f}s")
                time.sleep(actual_sleep)
                self.add_penalty(actual_sleep)
        else:
            self.add_penalty(1.0)

    # ----- Rate limiter health monitoring -----
    def log_ratelimit_health(self, prefix: str = "megafilter") -> None:
        """Мониторинг здоровья rate limiter"""
        if prefix == "quicknode":
            limiter = self._quicknode_limiter
        else:
            limiter = self._megafilter_limiter
        
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
