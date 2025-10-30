from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional


@dataclass(slots=True)
class AdaptiveParams:
    base_rps: float
    min_rps: float
    backoff_threshold: float  # decrease if 429 ratio > this
    recover_threshold: float  # increase if 429 ratio <= this
    decrease_step: float      # percentage of base to subtract, e.g. 0.25
    increase_step: float      # percentage of base to add, e.g. 0.10
    window: int               # last N responses to compute 429 ratio


class ApiRateLimiter:
    """
    Global token bucket + concurrency limiter + adaptive RPS.

    - Token bucket: capacity = effective_rps, refill rate = effective_rps tokens/sec
    - Global semaphore: limits max concurrent in-flight requests
    - Adaptive window: tracks last N responses, adjusts effective_rps based on 429 ratio

    All sleeps occur outside locks. Token refills under lock. Thread-safe.
    """

    def __init__(
        self,
        *,
        max_concurrency: int,
        adaptive: AdaptiveParams,
        log_fn: callable,
    ) -> None:
        self._lock = threading.Lock()
        self._sem = threading.Semaphore(max_concurrency)
        self._adaptive = adaptive
        self._log = log_fn

        self._effective_rps: float = max(adaptive.min_rps, adaptive.base_rps)
        self._capacity: float = self._effective_rps
        self._tokens: float = self._capacity
        self._last_refill: float = time.monotonic()

        self._codes: Deque[int] = deque(maxlen=adaptive.window)

    # ------------- Token bucket -------------
    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        # refill at rate = effective_rps tokens/sec
        self._tokens = min(self._capacity, self._tokens + self._effective_rps * elapsed)
        self._last_refill = now

    def _remove_token_if_available(self) -> bool:
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def acquire(self) -> float:
        """
        Acquire one token and semaphore. Returns required sleep seconds (0 if none).
        Must call release() after request completes.
        """
        self._sem.acquire()
        # compute waiting time without holding the lock while sleeping
        while True:
            with self._lock:
                if self._remove_token_if_available():
                    return 0.0
                # tokens short: compute next availability
                self._refill()
                need = 1.0 - self._tokens
                # avoid division by zero when effective_rps == 0 (should never be < min_rps)
                rate = max(self._effective_rps, 1e-6)
                sleep_for = max(need / rate, 0.0)
            # log outside the lock
            # Note: caller may log the throttling; return how long to sleep
            if sleep_for <= 0:
                # very small rounding; loop once more
                time.sleep(0.001)
            else:
                return sleep_for

    def release(self) -> None:
        self._sem.release()

    # ------------- Adaptive RPS -------------
    def record_status(self, http_status: int) -> None:
        with self._lock:
            self._codes.append(http_status)
            if len(self._codes) < self._codes.maxlen:
                return
            # compute 429 ratio
            total = len(self._codes)
            too_many = sum(1 for c in self._codes if c == 429)
            ratio = too_many / float(total) if total else 0.0

            old = self._effective_rps
            if ratio > self._adaptive.backoff_threshold:
                # decrease
                target = max(self._adaptive.min_rps, self._adaptive.base_rps * (1.0 - self._adaptive.decrease_step))
                new_rate = max(self._adaptive.min_rps, min(old, target))
                if new_rate < old:
                    self._effective_rps = new_rate
                    self._capacity = new_rate
                    self._log(f"[api] high 429 rate {int(ratio*100)}% → decrease RPS {old:.2f}→{new_rate:.2f}")
            elif ratio <= self._adaptive.recover_threshold and old < self._adaptive.base_rps:
                # recover (increase)
                target = min(self._adaptive.base_rps, old + self._adaptive.base_rps * self._adaptive.increase_step)
                if target > old:
                    self._effective_rps = target
                    self._capacity = target
                    self._log(f"[api] normalized {int(ratio*100)}% 429 → increase RPS {old:.2f}→{target:.2f}")

    def get_rate(self) -> float:
        with self._lock:
            return self._effective_rps
    
    def snapshot(self) -> dict:
        """Return current state snapshot for monitoring"""
        with self._lock:
            # Calculate 429 percentage from recent window
            total = len(self._codes)
            too_many = sum(1 for c in self._codes if c == 429) if self._codes else 0
            p429_pct = (100.0 * too_many / total) if total > 0 else 0.0
            
            return {
                "effective_rps": round(self._effective_rps, 3),
                "tokens": round(self._tokens, 2),
                "p429_pct": round(p429_pct, 1),
                "concurrency": getattr(self._sem, "_value", None),
            }
