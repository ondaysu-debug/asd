from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Tuple

import requests

from .config import Config
from .gecko import GeckoCache, fetch_ohlcv_49h
from .net_http import HttpClient
from .storage import Storage


@dataclass(slots=True)
class AlertInputs:
    chain: str
    pool: str
    url: str
    token_symbol: str
    token_addr: str
    liquidity: float


class Notifier:
    def __init__(self, cfg: Config, http_post: Callable[..., requests.Response] | None = None) -> None:
        self._cfg = cfg
        self._http_post = http_post

    def send(self, text: str) -> None:
        if not self._cfg.tg_bot_token or not self._cfg.tg_chat_id:
            print("TG>", text)
            return
        url = f"https://api.telegram.org/bot{self._cfg.tg_bot_token}/sendMessage"
        payload = {
            "chat_id": self._cfg.tg_chat_id,
            "text": text,
            "disable_web_page_preview": True,
            "parse_mode": self._cfg.tg_parse_mode or "Markdown",
        }
        try:
            if self._http_post is None:
                requests.post(url, json=payload, timeout=12)
            else:
                self._http_post(url, json=payload, timeout=12)
        except Exception as e:
            print("TG error:", e)


def should_alert(vol1h: float, prev48h: float, ratio_min: float) -> bool:
    return vol1h > 0.0 and prev48h > 0.0 and (vol1h > prev48h * max(0.0, float(ratio_min)))


def get_window_stats(
    cfg: Config,
    http: HttpClient,
    cache: GeckoCache,
    meta: AlertInputs,
) -> Tuple[float, float, str] | None:
    """
    Получает (vol1h, prev48h, source_tag) используя GeckoTerminal OHLCV.
    Возвращает None при нулевых значениях окна.
    """
    try:
        vol1h, prev48h = fetch_ohlcv_49h(cfg, http, meta.chain, meta.pool, cache)
    except Exception:
        vol1h, prev48h = (0.0, 0.0)
    if vol1h <= 0.0 and prev48h <= 0.0:
        return None
    return vol1h, prev48h, "GeckoTerminal-OHLCV"


def maybe_alert(
    cfg: Config,
    storage: Storage,
    cache: GeckoCache,
    http: HttpClient,
    notifier: Notifier,
    meta: AlertInputs,
) -> None:
    # Cooldown
    with storage.get_conn() as conn:
        last = storage.get_last_alert_ts(conn, meta.pool)
        if last:
            last_dt = datetime.fromtimestamp(int(last), tz=timezone.utc)
            if datetime.now(timezone.utc) - last_dt < timedelta(minutes=cfg.cooldown_min):
                return

        # Use window stats from GeckoTerminal OHLCV
        ws = get_window_stats(cfg, http, cache, meta)
        if ws is None:
            return
        vol1h, prev48h, source_tag = ws
        # Mark as seen regardless of alert outcome to avoid repeated OHLCV probes within TTL
        storage.mark_as_seen(conn, meta.pool)
        if prev48h <= 0:
            return

        if not should_alert(vol1h, prev48h, cfg.alert_ratio_min):
            return

        storage.set_last_alert_ts(conn, meta.pool, int(datetime.now(timezone.utc).timestamp()))

    prev48 = prev48h
    ratio = (vol1h / prev48) if prev48 > 0 else float("inf")
    # source_tag provided by get_window_stats

    text = (
        f"🚨 WAKE-UP ({meta.chain.capitalize()})\n"
        f"Pool: {_escape_md(meta.pool)}\n"
        f"Token: {_escape_md(meta.token_symbol or 'n/a')}\n"
        f"Contract: `{_escape_md(meta.token_addr or 'n/a')}`\n"
        f"Liquidity: ${_nice(meta.liquidity)}\n"
        f"1h Vol: ${_nice(vol1h)} ({source_tag})\n"
        f"Prev 48h Vol (excl. current 1h): ${_nice(prev48)}\n"
        f"Ratio 1h/prev48h: {ratio:.2f}x\n"
        f"Link: {_escape_md(meta.url)}"
    )
    notifier.send(text)


def _nice(x: float | int | None) -> str:
    try:
        v = float(x or 0.0)
        if v >= 1_000_000_000:
            return f"{v/1_000_000_000:.2f}B"
        if v >= 1_000_000:
            return f"{v/1_000_000:.2f}M"
        if v >= 1_000:
            return f"{v/1_000:.2f}k"
        return f"{v:.2f}"
    except Exception:
        return "n/a"


_MD_ESC = str.maketrans({"_": r"\_", "*": r"\*", "`": r"\`", "[": r"\[", "]": r"\]", "(": r"\(", ")": r"\)"})


def _escape_md(s: str) -> str:
    return s.translate(_MD_ESC) if s else s
