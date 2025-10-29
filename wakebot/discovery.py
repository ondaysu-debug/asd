from __future__ import annotations

from typing import Dict, List, Tuple

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


def gt_fetch_page(
    cfg: Config, http: HttpClient, chain: str, source: str, page: int
) -> Tuple[list[dict], Dict[str, int]]:
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
        # one page attempt, zero candidates, no filters counted
        return [], {"filtered_liq": 0, "filtered_tx": 0, "pages_fetched": 1}

    data = doc.get("data") or []
    included = doc.get("included") or []
    token_map: Dict[str, dict] = {
        item.get("id"): (item.get("attributes") or {})
        for item in included
        if (item.get("type") or "").lower() == "token"
    }

    out: list[dict] = []
    filtered_liq = 0
    filtered_tx = 0
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

        # count filter reasons (after TOKEN/native + base acceptance)
        failed_liq = not (cfg.liquidity_min <= liquidity <= cfg.liquidity_max)
        failed_tx = tx24h > cfg.tx24h_max
        if failed_liq or failed_tx:
            if failed_liq:
                filtered_liq += 1
            if failed_tx:
                filtered_tx += 1
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

    return out, {"filtered_liq": filtered_liq, "filtered_tx": filtered_tx, "pages_fetched": 1}


def gt_discover_new_pairs(cfg: Config, http: HttpClient, chain: str) -> Tuple[list[dict], Dict[str, int]]:
    """
    Discover TOKEN/native pools from GeckoTerminal using configured sources and pages.
    Sources: values from cfg.gecko_sources (comma-separated), supporting "new", "trending" (and raw "pools").
    Pages: 1..cfg.gecko_pages_per_chain for each source.
    """
    out: list[dict] = []
    stats = {"filtered_liq": 0, "filtered_tx": 0, "pages_fetched": 0}
    sources = cfg.gecko_sources_list or ["new"]
    for source in sources:
        for page in range(1, cfg.gecko_pages_per_chain + 1):
            items, st = gt_fetch_page(cfg, http, chain, source, page)
            stats["filtered_liq"] += st.get("filtered_liq", 0)
            stats["filtered_tx"] += st.get("filtered_tx", 0)
            stats["pages_fetched"] += st.get("pages_fetched", 0)
            if items:
                out.extend(items)

    # per-chain discovery summary
    print(
        f"[{chain}] sources={cfg.gecko_sources} "
        f"pages={cfg.gecko_pages_per_chain} page_size={cfg.gecko_page_size} "
        f"-> candidates={len(out)}"
    )
    return out, stats
