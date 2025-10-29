from wakebot.config import Config
from wakebot.gecko import GeckoCache, fetch_gecko_metrics


class DummyHttp:
    def __init__(self):
        self.calls = 0

    def get_json(self, url: str, timeout: float = 20.0):
        self.calls += 1
        return {
            "data": {
                "attributes": {
                    "volume_usd": {"h1": 10.0, "h48": 100.0},
                    "transactions": {"h1": {"buys": 3, "sells": 2}},
                }
            }
        }


def test_gecko_ttl_cache_avoids_repeat_calls():
    cfg = Config.load()
    http = DummyHttp()
    cache = GeckoCache(ttl_sec=60)

    v1 = fetch_gecko_metrics(cfg, http, "ethereum", "0xPOOL", cache)
    v2 = fetch_gecko_metrics(cfg, http, "ethereum", "0xPOOL", cache)

    assert http.calls == 1
    assert v1 == v2 == (10.0, 5, 100.0)
