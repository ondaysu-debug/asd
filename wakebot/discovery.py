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
                "pool_created_at": (attr.get("pool_created_at") or ""),
            }
        )

    return out, {"filtered_liq": filtered_liq, "filtered_tx": filtered_tx, "pages_fetched": 1}


def _dex_ids_for_chain(cfg: Config, http: HttpClient, chain: str) -> List[str]:
    gt_chain = _normalize_gt_chain(chain)
    url = f"{cfg.gecko_base}/networks/{gt_chain}/dexes?page=1&page_size=100"
    try:
        doc = http.gt_get_json(url, timeout=20.0) or {}
    except Exception:
        return []
    ids: List[str] = []
    for item in (doc.get("data") or []):
        if (item.get("type") or "").lower() == "dex":
            _id = item.get("id") or ""
            if _id:
                ids.append(_id)
    return ids


def _dex_pools_page(
    cfg: Config, http: HttpClient, chain: str, dex_id: str, page: int
) -> list[dict]:
    gt_chain = _normalize_gt_chain(chain)
    url = (
        f"{cfg.gecko_base}/networks/{gt_chain}/dexes/{dex_id}/pools?"
        f"page={page}&page_size={cfg.gecko_page_size}&include=base_token,quote_token"
    )
    try:
        doc = http.gt_get_json(url, timeout=20.0) or {}
    except Exception:
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

        failed_liq = not (cfg.liquidity_min <= liquidity <= cfg.liquidity_max)
        failed_tx = tx24h > cfg.tx24h_max
        if failed_liq or failed_tx:
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
                "pool_created_at": (attr.get("pool_created_at") or ""),
            }
        )
    return out


def gt_discover_by_source(
    cfg: Config, http: HttpClient, chain: str, source: str, start_page: int, page_limit: int
) -> list[dict]:
    s = (source or "").strip().lower()
    out: list[dict] = []
    if s in {"new", "trending", "pools"}:
        for page in range(start_page, max(start_page, 1) + max(0, page_limit) ):
            items, _ = gt_fetch_page(cfg, http, chain, s, page)
            if items:
                out.extend(items)
    elif s == "dexes":
        dex_ids = _dex_ids_for_chain(cfg, http, chain)
        if dex_ids:
            for dex_id in dex_ids:
                for page in range(start_page, max(start_page, 1) + max(0, page_limit)):
                    items = _dex_pools_page(cfg, http, chain, dex_id, page)
                    if items:
                        out.extend(items)
    else:
        # allow raw endpoint names behaving like pools
        for page in range(start_page, max(start_page, 1) + max(0, page_limit)):
            items, _ = gt_fetch_page(cfg, http, chain, s, page)
            if items:
                out.extend(items)

    # de-duplicate by pool id
    dedup: Dict[str, dict] = {}
    for it in out:
        pid = it.get("pool")
        if pid and pid not in dedup:
            dedup[pid] = it
    return list(dedup.values())


def gt_discover_candidates(
    cfg: Config, http: HttpClient, storage, chain: str, *, cycle_idx: int
) -> list[dict]:
    sources = cfg.gecko_sources_list or ["new"]
    if not sources:
        sources = ["new"]
    # rotate sources if enabled: pick exactly one for this cycle
    chosen_sources: List[str]
    if cfg.gecko_rotate_sources:
        idx = (max(0, cycle_idx - 1)) % len(sources)
        chosen_sources = [sources[idx]]
    else:
        chosen_sources = sources

    all_items: list[dict] = []
    with storage.get_conn() as conn:
        for source in chosen_sources:
            start_page = storage.get_progress(conn, chain, source)
            limit = cfg.gecko_dex_pages_per_chain if source.strip().lower() == "dexes" else cfg.gecko_pages_per_chain
            items = gt_discover_by_source(cfg, http, chain, source, start_page, limit)
            all_items.extend(items)
            # bump progress cursor for next cycle
            storage.bump_progress(conn, chain, source, start_page + max(1, limit))

    # summary
    print(
        f"[{chain}] sources={','.join(chosen_sources)} start_pages=vary page_size={cfg.gecko_page_size} -> candidates={len(all_items)}"
    )
    return all_items
