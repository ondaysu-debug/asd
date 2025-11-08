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
        
        # QuickNode rate limiter - ИСПРАВЛЕНО: адаптивно под план
        # Essential: 10M requests/month ≈ 3.8 requests/sec
        # Growth: 50M requests/month ≈ 19.2 requests/sec
        # Enterprise: custom (100+ requests/sec)
        plan_limits = {
            "essential": 3.8,
            "growth": 19.2,
            "enterprise": 100.0
        }
        
        quicknode_plan = getattr(cfg, 'quicknode_plan', 'essential')
        base_rps = plan_limits.get(quicknode_plan, 3.8)
        
        self._quicknode_limiter = ApiRateLimiter(
            max_concurrency=10,
            adaptive=AdaptiveParams(
                base_rps=base_rps,
                min_rps=base_rps * 0.1,
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

    # ----- QuickNode methods - ИСПРАВЛЕНО -----
    def _get_quicknode_url(self, network: str) -> str:
        """Получаем правильный URL для конкретной сети"""
        urls = {
            "solana": self._cfg.quicknode_solana_url,
            "ethereum": self._cfg.quicknode_ethereum_url,
            "base": self._cfg.quicknode_base_url,
            "bsc": self._cfg.quicknode_bsc_url
        }
        url = urls.get(network, "")
        if not url:
            self._log(f"[quicknode] WARNING: No URL configured for network: {network}")
        return url
    
    def quicknode_rpc_call(self, network: str, method: str, params: List = None, timeout: float = 30.0) -> dict[str, Any]:
        """
        УНИВЕРСАЛЬНЫЙ RPC вызов для любой сети
        ИСПРАВЛЕНО: Токен уже в URL, headers НЕ нужны
        Документация: https://docs.quicknode.com/core-products/rpc-endpoints
        """
        sleep_for = self._quicknode_limiter.acquire()
        if sleep_for > 0:
            self._log(f"[quicknode/{network}] throttling sleep {sleep_for:.3f}s")
            time.sleep(min(sleep_for, 5.0))
        
        try:
            session = self._session()
            url = self._get_quicknode_url(network)
            
            if not url:
                return {}
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params or []
            }
            
            # ИСПРАВЛЕНО: QuickNode RPC НЕ требует Authorization header
            # Токен уже в URL: https://your-endpoint.quiknode.pro/token/
            headers = {"Content-Type": "application/json"}
            
            r = session.post(url, json=payload, headers=headers, timeout=timeout)
            status = r.status_code
            self._quicknode_limiter.record_status(status)

            if status == 429:
                self._handle_quicknode_rate_limit(r)
            
            r.raise_for_status()
            result = r.json() or {}
            return result.get('result', {}) if 'result' in result else result
            
        except Exception as e:
            self._log(f"[quicknode/{network}] RPC error: {e}")
            return {}
        finally:
            self._quicknode_limiter.release()
            self._cycle_requests += 1
    
    def quicknode_solana_rpc(self, payload: Dict, timeout: float = 30.0) -> dict[str, Any]:
        """
        Solana RPC - обертка для обратной совместимости
        """
        method = payload.get('method', '')
        params = payload.get('params', [])
        response = self.quicknode_rpc_call('solana', method, params, timeout)
        # Возвращаем в старом формате для совместимости
        return {'result': response} if response else {}
    
    def quicknode_evm_rpc(self, network: str, payload: Dict, timeout: float = 30.0) -> dict[str, Any]:
        """
        EVM RPC - обертка для обратной совместимости
        ИСПРАВЛЕНО: использует универсальный quicknode_rpc_call
        """
        method = payload.get('method', '')
        params = payload.get('params', [])
        response = self.quicknode_rpc_call(network, method, params, timeout)
        # Возвращаем в старом формате для совместимости
        return {'result': response} if response else {}
    
    def quicknode_batch_rpc(self, network: str, requests: List[Dict], timeout: float = 60.0) -> list[dict]:
        """
        Batch RPC запросы к QuickNode
        ИСПРАВЛЕНО: До 100 запросов в батче, токен в URL
        Документация: https://docs.quicknode.com/core-products/batch-requests
        """
        # QuickNode поддерживает до 100 запросов в батче
        if len(requests) > 100:
            self._log(f"[quicknode/batch] WARNING: {len(requests)} requests, max 100. Splitting...")
            # Разбиваем на батчи по 100
            all_responses = []
            for i in range(0, len(requests), 100):
                batch = requests[i:i+100]
                responses = self.quicknode_batch_rpc(network, batch, timeout)
                all_responses.extend(responses)
            return all_responses
        
        sleep_for = self._quicknode_limiter.acquire()
        if sleep_for > 0:
            self._log(f"[quicknode/{network}/batch] throttling sleep {sleep_for:.3f}s")
            time.sleep(min(sleep_for, 5.0))
        
        try:
            session = self._session()
            url = self._get_quicknode_url(network)
            
            if not url:
                return []
            
            # ИСПРАВЛЕНО: QuickNode RPC НЕ требует Authorization header
            headers = {"Content-Type": "application/json"}
            
            # Batch запрос - массив RPC запросов
            r = session.post(url, json=requests, headers=headers, timeout=timeout)
            status = r.status_code
            self._quicknode_limiter.record_status(status)

            if status == 429:
                self._handle_quicknode_rate_limit(r)
            
            r.raise_for_status()
            response = r.json()
            
            # Batch response - массив RPC responses
            return response if isinstance(response, list) else []
            
        except Exception as e:
            self._log(f"[quicknode/{network}/batch] RPC error: {e}")
            return []
        finally:
            self._quicknode_limiter.release()
            self._cycle_requests += len(requests)  # Учитываем все запросы в батче
    
    def _handle_quicknode_rate_limit(self, response):
        """
        Обработка rate limiting от QuickNode
        ИСПРАВЛЕНО: QuickNode использует стандартный Retry-After
        """
        self._cycle_429 += 1
        retry_after = response.headers.get("Retry-After")
        
        if retry_after:
            sleep_s = _parse_retry_after(retry_after)
            if sleep_s and sleep_s > 0:
                # QuickNode может давать большие Retry-After, лимитируем
                actual_sleep = min(sleep_s, 60.0)  # Максимум 60 секунд
                self._log(f"[quicknode] 429 Retry-After {sleep_s:.3f}s (sleeping {actual_sleep:.1f}s)")
                time.sleep(actual_sleep)
                self.add_penalty(actual_sleep)
        else:
            # Дефолтная пауза при 429 без Retry-After
            self._log(f"[quicknode] 429 without Retry-After, using default 5s pause")
            time.sleep(5.0)
            self.add_penalty(5.0)

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
