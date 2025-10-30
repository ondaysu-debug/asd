from __future__ import annotations

from typing import Tuple
from datetime import datetime, timedelta, timezone

from .config import Config
from .net_http import HttpClient
from .gecko import GeckoCache
import random


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


def _validate_cmc_pairs_doc(doc: dict) -> bool:
    if not isinstance(doc, dict):
        return False
    data = doc.get("data")
    if not isinstance(data, list):
        return False
    for item in data:
        if not isinstance(item, dict):
            return False
        has_id = any(k in item for k in ("pair_address", "id", "pairId"))
        if not has_id:
            return False
    return True


def _validate_cmc_ohlcv_doc(doc: dict) -> bool:
    if not isinstance(doc, dict):
        return False
    data = doc.get("data")
    if not data:
        return False
    attrs = (data.get("attributes") or {}) if isinstance(data, dict) else {}
    candles = attrs.get("candles") or attrs.get("ohlcv_list")
    if not isinstance(candles, list):
        return False
    for c in candles:
        if not (isinstance(c, list) and len(c) >= 6):
            return False
    return True


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
        return float(cached[0]), float(cached[1]), True, "cache"

    cmc_chain = cfg.chain_slugs.get((chain or "").strip().lower(), chain) if cfg.chain_slugs else chain
    # Use CMC DEX API v4 OHLCV endpoint
    # NOTE: 2025 CMC DEX API docs: pairs OHLCV via /v4/dex/pairs/ohlcv/latest using params below
    url = f"{cfg.cmc_dex_base}/v4/dex/pairs/ohlcv/latest"
    params = {"pair_address": pool_id, "timeframe": "1h", "aggregate": 1, "limit": 25}

    try:
        doc = http.cmc_get_json(url, params=params, timeout=20.0) or {}
        if not _validate_cmc_ohlcv_doc(doc):
            # schema change or unexpected response
            print(f"[cmc][validate] unexpected ohlcv schema for pair={pool_id}; fallback? {cfg.allow_gt_ohlcv_fallback}")
            # continue to fallback path
            raise ValueError("invalid cmc ohlcv schema")
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

                vol1h_f, prev24h_f, ok_age_f = _gt_25h(cfg, http, chain, pool_id, cache)
                # Data quality log if both existed (in this branch we had no candles, so skip DQ)
                cache.set(key, (vol1h_f, prev24h_f))
                return vol1h_f, prev24h_f, ok_age_f, "CMC→GT fallback"
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
        source = "CMC DEX"
        # Data-quality sampling: compare with GT ~5% of the time if allowed
        try:
            if cfg.allow_gt_ohlcv_fallback and random.random() < 0.05:
                from .gecko import fetch_gt_ohlcv_25h as _gt_25h

                vol1h_gt, prev24_gt, _ = _gt_25h(cfg, http, chain, pool_id, cache)
                dv1 = abs(float(vol1h) - float(vol1h_gt))
                dv1_rel = dv1 / max(1.0, float(vol1h))
                dprev = abs(float(prev24h) - float(prev24_gt))
                dprev_rel = dprev / max(1.0, float(prev24h))
                print(
                    f"[dq] {chain}/{pool_id} v1h CMC={vol1h:.2f} GT={vol1h_gt:.2f} Δ={dv1:.2f} ({dv1_rel:.1%}); "
                    f"prev24 CMC={prev24h:.2f} GT={prev24_gt:.2f} Δ={dprev:.2f} ({dprev_rel:.1%})"
                )
                if max(dv1_rel, dprev_rel) > float(getattr(cfg, 'dq_warn_threshold', 0.25)):
                    print(f"[dq][warn] discrepancy >{int(100*getattr(cfg, 'dq_warn_threshold', 0.25))}% for {chain}/{pool_id}")
        except Exception:
            pass
        return vol1h, prev24h, ok_age, source
    except Exception:
        if cfg.allow_gt_ohlcv_fallback:
            try:
                from .gecko import fetch_gt_ohlcv_25h as _gt_25h

                vol1h_f, prev24h_f, ok_age_f = _gt_25h(cfg, http, chain, pool_id, cache)
                cache.set(key, (vol1h_f, prev24h_f))
                # DQ log not possible here as CMC failed
                return vol1h_f, prev24h_f, ok_age_f, "CMC→GT fallback"
            except Exception:
                pass
        return 0.0, 0.0, False, "CMC DEX"
