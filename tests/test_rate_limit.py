import time

from wakebot.rate_limit import AdaptiveParams, DexscreenerLimiter


def test_token_bucket_limits_throughput():
    # RPS=2, 5 sequential acquires should take at least ~1.5s (initial token available, then ~0.5s each)
    logs = []
    limiter = DexscreenerLimiter(
        max_concurrency=10,
        adaptive=AdaptiveParams(
            base_rps=2.0,
            min_rps=1.0,
            backoff_threshold=0.9,
            recover_threshold=0.1,
            decrease_step=0.25,
            increase_step=0.10,
            window=10,
        ),
        log_fn=logs.append,
    )

    start = time.monotonic()
    total_sleep = 0.0
    for _ in range(5):
        sleep_for = limiter.acquire()
        total_sleep += sleep_for
        if sleep_for > 0:
            time.sleep(sleep_for)
        limiter.release()
    elapsed = time.monotonic() - start
    assert elapsed >= 1.0  # conservative lower bound


def test_adaptive_decrease_and_recover():
    logs = []
    limiter = DexscreenerLimiter(
        max_concurrency=2,
        adaptive=AdaptiveParams(
            base_rps=8.0,
            min_rps=1.0,
            backoff_threshold=0.3,
            recover_threshold=0.1,
            decrease_step=0.25,
            increase_step=0.10,
            window=10,
        ),
        log_fn=logs.append,
    )

    # fill window with many 429 to trigger decrease
    for _ in range(7):
        limiter.record_status(429)
    for _ in range(3):
        limiter.record_status(200)
    rate_after_decrease = limiter.get_rate()
    assert rate_after_decrease < 8.0

    # now normalize with mostly 200s
    for _ in range(9):
        limiter.record_status(200)
    limiter.record_status(429)
    rate_after_recover = limiter.get_rate()
    assert rate_after_recover >= rate_after_decrease
