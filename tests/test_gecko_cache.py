from wakebot.config import Config
from wakebot.gecko import GeckoCache, fetch_ohlcv_49h


class DummyHttp:
    def __init__(self):
        self.calls = 0

    def gt_get_json(self, url: str, timeout: float = 20.0):
        self.calls += 1
        # last candle volume = 10.0, previous two candles sum = 100.0
        return {
            "data": {
                "attributes": {
                    "candles": [
                        [0, 0, 0, 0, 0, 50.0],
                        [1, 0, 0, 0, 0, 50.0],
                        [2, 0, 0, 0, 0, 10.0],
                    ]
                }
            }
        }


def test_gecko_ttl_cache_avoids_repeat_calls():
    cfg = Config.load()
    http = DummyHttp()
    cache = GeckoCache(ttl_sec=60)

    v1 = fetch_ohlcv_49h(cfg, http, "ethereum", "0xPOOL", cache)
    v2 = fetch_ohlcv_49h(cfg, http, "ethereum", "0xPOOL", cache)

    assert http.calls == 1
    assert v1 == v2 == (10.0, 100.0)
