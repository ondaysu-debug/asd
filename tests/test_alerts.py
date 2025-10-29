from datetime import datetime, timedelta, timezone

from wakebot.alerts import AlertInputs, Notifier, should_alert, maybe_alert
from wakebot.config import Config
from wakebot.gecko import GeckoCache
from wakebot.storage import Storage


class DummyNotifier(Notifier):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.sent = []

    def send(self, text: str) -> None:
        self.sent.append(text)


def make_cfg(tmp_path, cooldown_min=0):
    return Config(
        tg_bot_token="",
        tg_chat_id="",
        tg_parse_mode="Markdown",
        dexscreener_base="https://example.com",
        gecko_base="https://example.com",
        market_cap_min=50_000,
        market_cap_max=800_000,
        tx24h_max=2000,
        chains=["ethereum"],
        cooldown_min=cooldown_min,
        loop_seconds=60,
        chain_scan_workers=2,
        alert_fetch_workers=4,
        max_cycles=0,
        save_candidates=False,
        candidates_path=tmp_path / "candidates.jsonl",
        scan_by_dex=True,
        fallback_bucketed_search=True,
        bucket_alphabet="ab",
        use_two_char_buckets=False,
        max_buckets_per_chain=10,
        bucket_delay_sec=0.0,
        max_pairs_per_dex=100,
        bucket_search_target=0,
        bucket_search_workers=4,
        bucket_retry_limit=1,
        gecko_ttl_sec=60,
        ds_calls_per_sec_base=5.0,
        ds_calls_per_sec_min=1.0,
        ds_max_concurrency=4,
        ds_adaptive_window=10,
        ds_backoff_threshold=0.3,
        ds_recover_threshold=0.1,
        ds_decrease_step=0.25,
        ds_increase_step=0.10,
        ds_retry_after_cap_s=1.0,
        db_path=tmp_path / "state.sqlite",
    )


def test_should_alert_rule_edges():
    # prev48 = max(100-100,0) = 0 => alert
    assert should_alert(100.0, 100.0) is True
    # vol1h==prev48 -> no alert
    assert should_alert(50.0, 100.0) is False
    # slightly greater than prev48 -> alert
    assert should_alert(50.1, 100.0) is True
    assert should_alert(0.0, 0.0) is False


def test_maybe_alert_with_gecko_then_cooldown(tmp_path):
    cfg = make_cfg(tmp_path, cooldown_min=1)
    storage = Storage(cfg)
    cache = GeckoCache(cfg.gecko_ttl_sec)

    def fetch_gecko(chain, pool):
        return (60.0, 10, 100.0)

    notifier = DummyNotifier(cfg)

    meta = AlertInputs(
        chain="ethereum",
        pool="0xPOOL",
        url="https://dexscreener.com/ethereum/0xPOOL",
        token_symbol="TKN",
        token_addr="0xToken",
        fdv=100000.0,
        ds_vol1h=0.0,
        ds_vol48h=0.0,
    )

    maybe_alert(cfg, storage, cache, fetch_gecko, notifier, meta)
    assert len(notifier.sent) == 1

    # cooldown immediate second alert should be blocked
    maybe_alert(cfg, storage, cache, fetch_gecko, notifier, meta)
    assert len(notifier.sent) == 1


def test_maybe_alert_fallback_to_ds_and_vol48_zero_no_alert(tmp_path):
    cfg = make_cfg(tmp_path)
    storage = Storage(cfg)
    cache = GeckoCache(cfg.gecko_ttl_sec)

    def fetch_gecko(chain, pool):
        return (0.0, 0, 0.0)  # gecko failed

    notifier = DummyNotifier(cfg)

    meta = AlertInputs(
        chain="ethereum",
        pool="0xPOOL",
        url="https://dexscreener.com/ethereum/0xPOOL",
        token_symbol="TKN",
        token_addr="0xToken",
        fdv=100000.0,
        ds_vol1h=60.0,
        ds_vol48h=0.0,  # zero => no alert
    )

    maybe_alert(cfg, storage, cache, fetch_gecko, notifier, meta)
    assert len(notifier.sent) == 0
