from __future__ import annotations

from typing import Dict, List

from .config import Config
from .filters import is_base_token_acceptable, is_token_native_pair, pool_data_filters
from .gecko import _normalize_gt_chain
from .net_http import HttpClient


def _source_to_endpoint(source: str) -> str:
    s = (source or "").strip().lower()
    if s == "new":
        return "new_pools"
    if s == "trending":
        return "trending_pools"
    return s  # allow raw values like "pools"


def gt_fetch_page(cfg: Config, http: HttpClient, chain: str, source: str, page: int) -> list[dict]:
    gt_chain = _normalize_gt_chain(chain)
    endpoint = _source_to_endpoint(source)
    url = (
        f"{cfg.gecko_base}/networks/{gt_chain}/{endpoint}?"
        f"page={page}&page_size={cfg.gecko_page_size}&include=base_token,quote_token,dex"
    )
    try:
        doc = http.gt_get_json(url, timeout=20.0) or {}
    except Exception as e:
        print(f"[{chain}] {endpoint} page {page} error: {e}")
        return []

    data = doc.get("data") or []
    included = doc.get("included") or []
    token_map: Dict[str, dict] = {
        item.get("id"): (item.get("attributes") or {})
        for item in included
        if (item.get("type") or "").lower() == "token"
    }

    out: list[dict] = []
    seen: set[str] = set()
    for pool in data:
        if (pool.get("type") or "").lower() != "pool":
            continue
        pool_id = pool.get("id") or ""
        if not pool_id or pool_id in seen:
            continue
        seen.add(pool_id)

        attr = pool.get("attributes") or {}
        rel = pool.get("relationships") or {}

        base_rel = ((rel.get("base_token") or {}).get("data") or {})
        quote_rel = ((rel.get("quote_token") or {}).get("data") or {})
        base_tok = token_map.get(base_rel.get("id") or "", {})
        quote_tok = token_map.get(quote_rel.get("id") or "", {})

        ok, token_side, native_side = is_token_native_pair(chain, base_tok, quote_tok)
        if not ok:
            continue
        if not is_base_token_acceptable(chain, token_side):
            continue

        liquidity = float(attr.get("reserve_in_usd") or 0.0)
        tx24 = (attr.get("transactions") or {}).get("h24") or {}
        tx24h = int((tx24.get("buys") or 0) + (tx24.get("sells") or 0))
        if not pool_data_filters(liquidity, cfg.liquidity_min, cfg.liquidity_max, tx24h, cfg.tx24h_max):
            continue

        out.append(
            {
                "chain": chain,
                "pool": pool_id,
                "url": f"https://www.geckoterminal.com/{gt_chain}/pools/{pool_id}",
                "baseSymbol": (token_side.get("symbol") or ""),
                "baseAddr": (token_side.get("address") or ""),
                "quoteSymbol": (native_side.get("symbol") or ""),
                "quoteAddr": (native_side.get("address") or ""),
                "liquidity": liquidity,
                "tx24h": tx24h,
            }
        )

    return out


def gt_discover_new_pairs(cfg: Config, http: HttpClient, chain: str) -> list[dict]:
    """
    Discover TOKEN/native pools from GeckoTerminal using configured sources and pages.
    Sources: values from cfg.gecko_sources (comma-separated), supporting "new", "trending" (and raw "pools").
    Pages: 1..cfg.gecko_pages_per_chain for each source.
    """
    out: list[dict] = []
    sources = cfg.gecko_sources_list or ["new"]
    for source in sources:
        for page in range(1, cfg.gecko_pages_per_chain + 1):
            items = gt_fetch_page(cfg, http, chain, source, page)
            if items:
                out.extend(items)
    return out
