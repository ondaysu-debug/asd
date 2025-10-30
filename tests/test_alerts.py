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
        cmc_dex_base="https://api.coinmarketcap.com/dexer/v3",
        cmc_dex_base_alt="",
        cmc_api_key="",
        gecko_base="https://example.com",
        allow_gt_ohlcv_fallback=False,
        liquidity_min=50_000,
        liquidity_max=800_000,
        tx24h_max=2000,
        chains=["ethereum"],
        cmc_calls_per_min=28,
        cmc_retry_after_cap_s=1.0,
        gecko_calls_per_min=28,
        gecko_retry_after_cap_s=1.0,
        gecko_ttl_sec=60,
        cmc_sources="new,trending",
        cmc_rotate_sources=True,
        cmc_pages_per_chain=1,
        cmc_dex_pages_per_chain=1,
        cmc_page_size=50,
        gecko_sources="new,trending",
        gecko_rotate_sources=True,
        gecko_pages_per_chain=1,
        gecko_dex_pages_per_chain=1,
        gecko_page_size=50,
        max_ohlcv_probes_cap=30,
        cmc_safety_budget=4,
        gecko_safety_budget=4,
        min_ohlcv_probes=3,
        max_ohlcv_probes=30,
        cooldown_min=cooldown_min,
        loop_seconds=60,
        chain_scan_workers=2,
        alert_fetch_workers=4,
        max_cycles=0,
        alert_ratio_min=0.5,
        min_prev24_usd=1000,
        revival_min_age_days=7,
        dq_discrepancy_threshold=0.25,
        seen_ttl_min=15,
        seen_ttl_sec=900,
        save_candidates=False,
        candidates_path=tmp_path / "candidates.jsonl",
        db_path=tmp_path / "state.sqlite",
    )


def test_should_alert_rule_edges():
    # vol1h must exceed prev48h and both > 0
    assert should_alert(100.0, 99.0, 1.0) is True
    assert should_alert(50.0, 50.0, 1.0) is False
    assert should_alert(50.1, 50.0, 1.0) is True
    assert should_alert(0.0, 0.0, 1.0) is False


class DummyHttp:
    def __init__(self, v1: float, prev48: float):
        self.v1 = v1
        self.prev48 = prev48

    def gt_get_json(self, url: str, timeout: float = 20.0):
        # Build candles that sum to prev48 for previous window and v1 for last hour
        prev = []
        remaining = self.prev48
        # simple two-candle split
        a = max(0.0, remaining - 1.0)
        b = remaining - a
        prev = [
            [0, 0, 0, 0, 0, a],
            [1, 0, 0, 0, 0, b],
        ]
        last = [2, 0, 0, 0, 0, self.v1]
        return {
            "data": {"attributes": {"candles": prev + [last]}}
        }


def test_maybe_alert_with_gecko_then_cooldown(tmp_path):
    cfg = make_cfg(tmp_path, cooldown_min=1)
    storage = Storage(cfg)
    cache = GeckoCache(cfg.gecko_ttl_sec)
    http = DummyHttp(60.0, 100.0)
    notifier = DummyNotifier(cfg)

    meta = AlertInputs(
        chain="ethereum",
        pool="0xPOOL",
        url="https://www.geckoterminal.com/eth/pools/0xPOOL",
        token_symbol="TKN",
        token_addr="0xToken",
        liquidity=100000.0,
    )

    maybe_alert(cfg, storage, cache, http, notifier, meta)
    assert len(notifier.sent) == 1

    # cooldown immediate second alert should be blocked
    maybe_alert(cfg, storage, cache, http, notifier, meta)
    assert len(notifier.sent) == 1


def test_maybe_alert_no_alert_when_zero_window(tmp_path):
    cfg = make_cfg(tmp_path)
    storage = Storage(cfg)
    cache = GeckoCache(cfg.gecko_ttl_sec)
    http = DummyHttp(0.0, 0.0)
    notifier = DummyNotifier(cfg)

    meta = AlertInputs(
        chain="ethereum",
        pool="0xPOOL",
        url="https://www.geckoterminal.com/eth/pools/0xPOOL",
        token_symbol="TKN",
        token_addr="0xToken",
        liquidity=100000.0,
    )

    maybe_alert(cfg, storage, cache, http, notifier, meta)
    assert len(notifier.sent) == 0
