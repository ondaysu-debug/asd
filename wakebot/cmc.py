from __future__ import annotations

from typing import Tuple
from datetime import datetime, timedelta, timezone

from .config import Config
from .net_http import HttpClient
from .gecko import GeckoCache


def _parse_ts(ts_val) -> datetime | None:
    try:
        # CMC typically returns UNIX seconds
        ts = int(ts_val)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        try:
            # ISO-8601 fallback
            s = str(ts_val)
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None


def fetch_cmc_ohlcv_25h(
    cfg: Config,
    http: HttpClient,
    chain: str,
    pool_id: str,
    cache: GeckoCache,
    pool_created_at: str | None = None,
) -> Tuple[float, float, bool, str]:
    """
    Fetch 25 hourly candles and compute (vol1h, prev24h, ok_age).
    Uses TTL cache provided (reuses GeckoCache type for simplicity).
    """
    key = (f"cmc:{chain}", pool_id)
    cached = cache.get(key)  # type: ignore
    if cached is not None and isinstance(cached, tuple) and len(cached) == 2:
        # Backward data shape from GeckoCache: (a, b)
        # We tagged with cmc: prefix; if present, treat as (vol1h, prev24h)
        return float(cached[0]), float(cached[1]), True, "CMC DEX"

    # Prefer configured slug mapping. Note: Public CMC doc may reference /v4/dex/pairs/ohlcv/latest
    # with params (pair_address, timeframe=1h, limit=25). Our production path uses dexer/v3 style.
    cmc_chain = (cfg.chain_slugs or {}).get((chain or "").strip().lower(), (chain or "").strip().lower())
    url = f"{cfg.cmc_dex_base}/{cmc_chain}/pools/{pool_id}/ohlcv/hour?aggregate=1&limit=25"

    try:
        doc = http.cmc_get_json(url, timeout=20.0) or {}
        attrs = ((doc.get("data") or {}).get("attributes") or {}) if isinstance(doc.get("data"), dict) else {}
        # Accept several shapes
        candles = (
            attrs.get("ohlcv_list")
            or attrs.get("candles")
            or (doc.get("data") or {}).get("candles")
            or doc.get("candles")
            or []
        )
        if not isinstance(candles, list) or len(candles) < 2:
            # fallback if no data
            if cfg.allow_gt_ohlcv_fallback:
                from .gecko import fetch_gt_ohlcv_25h as _gt_25h

                vol1h_f, prev24h_f = _gt_25h(cfg, http, chain, pool_id, cache)
                cache.set(key, (vol1h_f, prev24h_f))
                return vol1h_f, prev24h_f, True, "CMC→GT fallback"
            return 0.0, 0.0, False, "CMC DEX"

        # Expect candle format [ts, o, h, l, c, v]
        vols: list[float] = []
        first_dt: datetime | None = None
        for c in candles:
            try:
                if isinstance(c, (list, tuple)) and len(c) >= 6:
                    vols.append(float(c[5]))
                    if first_dt is None:
                        d = _parse_ts(c[0])
                        if d is not None:
                            first_dt = d
            except Exception:
                continue
        if not vols:
            return 0.0, 0.0, False
        vol1h = float(vols[-1])
        prev24h = float(sum(vols[-25:-1])) if len(vols) >= 2 else 0.0

        # Age
        ok_age = False
        now_dt = datetime.now(timezone.utc)
        if pool_created_at:
            try:
                created_dt = datetime.fromisoformat(pool_created_at.replace("Z", "+00:00"))
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                ok_age = (now_dt - created_dt) >= timedelta(days=int(cfg.revival_min_age_days))
            except Exception:
                ok_age = False
        if not ok_age and first_dt is not None:
            ok_age = (now_dt - first_dt) >= timedelta(days=int(cfg.revival_min_age_days))

        cache.set(key, (vol1h, prev24h))
        return vol1h, prev24h, ok_age, "CMC DEX"
    except Exception:
        if cfg.allow_gt_ohlcv_fallback:
            try:
                from .gecko import fetch_gt_ohlcv_25h as _gt_25h

                vol1h_f, prev24h_f = _gt_25h(cfg, http, chain, pool_id, cache)
                cache.set(key, (vol1h_f, prev24h_f))
                return vol1h_f, prev24h_f, True, "CMC→GT fallback"
            except Exception:
                pass
        return 0.0, 0.0, False, "CMC DEX"
