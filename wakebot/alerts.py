from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Tuple

import requests

from .config import Config
from .gecko import GeckoCache, fetch_gecko_metrics
from .storage import Storage


@dataclass(slots=True)
class AlertInputs:
    chain: str
    pool: str
    url: str
    token_symbol: str
    token_addr: str
    fdv: float
    ds_vol1h: float
    ds_vol48h: float


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


def should_alert(vol1h: float, vol48h: float) -> bool:
    prev48 = max(vol48h - vol1h, 0.0)
    return vol1h > 0.0 and vol1h > prev48


def get_window_stats(
    cfg: Config,
    meta: AlertInputs,
    fetch_window: Callable[[str, str], Tuple[float, int, float]],
) -> Tuple[float, int, float, str] | None:
    """
    Пытается получить (vol1h, tx1h, vol48h, source_tag).
    1) Пробуем REST-провайдер (оборачивается вызывающим кодом)
    2) При ошибке или нулях: fallback на DexScreener-поля из meta (vol1h_ds/vol48h_ds)
    """
    try:
        vol1h, tx1h, vol48h = fetch_window(meta.chain, meta.pool)
    except Exception as e:
        print(f"[onchain] fallback to DexScreener for {meta.chain}/{meta.pool}: {e}")
        vol1h, tx1h, vol48h = (0.0, 0, 0.0)

    if (vol1h, tx1h, vol48h) != (0.0, 0, 0.0):
        return vol1h, tx1h, vol48h, "CoinGeckoREST"

    # Fallback to DexScreener metrics from discovery candidate
    vol1h = float(meta.ds_vol1h or 0.0)
    vol48h = float(meta.ds_vol48h or 0.0)
    if vol1h <= 0 and vol48h <= 0:
        return None
    return vol1h, 0, vol48h, "DexScreener"


def maybe_alert(
    cfg: Config,
    storage: Storage,
    cache: GeckoCache,
    fetch_gecko: Callable[[str, str], Tuple[float, int, float]],
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

        # Use window stats from REST provider with DexScreener fallback
        ws = get_window_stats(cfg, meta, fetch_gecko)
        if ws is None:
            return
        vol1h, tx1h, vol48h, source_tag = ws
        if vol48h <= 0:
            return

        if not should_alert(vol1h, vol48h):
            return

        storage.set_last_alert_ts(conn, meta.pool, int(datetime.now(timezone.utc).timestamp()))

    prev48 = max(vol48h - vol1h, 0.0)
    ratio = (vol1h / prev48) if prev48 > 0 else float("inf")
    # source_tag provided by get_window_stats

    text = (
        f"🚨 WAKE-UP ({meta.chain.capitalize()})\n"
        f"Pool: {meta.pool}\n"
        f"Token: {meta.token_symbol or 'n/a'}\n"
        f"Contract: `{meta.token_addr or 'n/a'}`\n"
        f"FDV: ${_nice(meta.fdv)}\n\n"
        f"1h Vol: ${_nice(vol1h)} ({source_tag})\n"
        f"Prev 48h Vol (excl. current 1h): ${_nice(prev48)}\n"
        f"Ratio 1h/prev48h: {ratio:.2f}x\n"
        f"Link: {meta.url}"
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
