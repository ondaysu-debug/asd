from __future__ import annotations

from typing import Dict, List, Tuple

from .config import Config
from .filters import is_base_token_acceptable, is_token_native_pair, pool_data_filters
from .gecko import _normalize_gt_chain
from .net_http import HttpClient


def _validate_cmc_pairs_doc(doc: dict) -> bool:
    """
    Validate CMC discovery response structure.
    Expected: {"data": [...]} where each item has pair identifiers and token info.
    """
    if not isinstance(doc, dict):
        return False
    data = doc.get("data") or doc.get("result") or doc.get("items")
    if not isinstance(data, list):
        return False
    
    # Each element should have at least one identifier for the pair
    for item in data:
        if not isinstance(item, dict):
            return False
        # Check for any common pair ID fields
        has_id = any(k in item for k in ("pair_address", "id", "pairId", "pool_id", "address", "poolAddress"))
        if not has_id:
            return False
    
    return True


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


# ---------------- CMC DEX discovery ----------------

def _normalize_cmc_chain(cfg: Config, chain: str) -> list[str]:
    """
    Return list of chain slug variants to try (for fallback on 400).
    Uses cmc_chain_slugs mapping from config with multiple variants per chain.
    """
    s = (chain or "").strip().lower()
    if cfg.cmc_chain_slugs and s in cfg.cmc_chain_slugs:
        return cfg.cmc_chain_slugs[s]
    # Fallback: try simple chain slug from chain_slugs, then raw chain
    if cfg.chain_slugs and s in cfg.chain_slugs:
        return [cfg.chain_slugs[s]]
    return [s]


def _cmc_pool_url_hint(pool_id: str) -> str:
    # Best-effort clickable hint if CMC UI path differs
    try:
        pid = (pool_id or "").strip()
        if pid:
            return f"https://coinmarketcap.com/dexscan/pairs/{pid}"
    except Exception:
        pass
    return ""


def _extract_token(item: dict, prefix: str) -> dict:
    tok = {}
    # flat style
    tok["address"] = item.get(f"{prefix}_address") or item.get(f"{prefix}Address") or ""
    tok["symbol"] = item.get(f"{prefix}_symbol") or item.get(f"{prefix}Symbol") or ""
    # nested style
    nested = item.get(prefix) or item.get(f"{prefix}_token") or {}
    if not tok["address"]:
        tok["address"] = nested.get("address") or nested.get("contract_address") or ""
    if not tok["symbol"]:
        tok["symbol"] = nested.get("symbol") or nested.get("ticker") or ""
    return tok


def _extract_common_fields(pool: dict) -> tuple[str, dict, dict, float, int, str]:
    # pool id
    pool_id = pool.get("id") or pool.get("pool_id") or pool.get("address") or pool.get("poolAddress") or ""
    base_tok = _extract_token(pool, "base")
    quote_tok = _extract_token(pool, "quote")
    # liquidity
    liq = (
        pool.get("reserve_in_usd")
        or pool.get("liquidity_in_usd")
        or pool.get("liquidity_usd")
        or pool.get("liquidity")
        or 0.0
    )
    try:
        liquidity = float(liq)
    except Exception:
        liquidity = 0.0
    # tx24h
    tx24h = 0
    tx = pool.get("transactions") or pool.get("tx") or {}
    if isinstance(tx, dict):
        h24 = tx.get("h24") or tx.get("24h") or {}
        try:
            buys = int(h24.get("buys") or h24.get("buy") or pool.get("buys24h") or 0)
            sells = int(h24.get("sells") or h24.get("sell") or pool.get("sells24h") or 0)
            tx24h = buys + sells
        except Exception:
            tx24h = int(pool.get("tx24h") or 0)
    else:
        try:
            tx24h = int(pool.get("tx24h") or 0)
        except Exception:
            tx24h = 0
    # created at
    pool_created_at = pool.get("pool_created_at") or pool.get("created_at") or pool.get("createdAt") or ""
    return pool_id, base_tok, quote_tok, liquidity, tx24h, pool_created_at


def cmc_discover_by_source(
    cfg: Config,
    http: HttpClient,
    chain: str,
    source: str,
    start_page: int,
    page_limit: int,
) -> tuple[list[dict], dict[str, int]]:
    cmc_chain_variants = _normalize_cmc_chain(cfg, chain)
    s = (source or "").strip().lower()
    out: list[dict] = []
    scanned_pairs = 0
    pages_done = 0

    def _fetch_page_with_fallback(base_url_template: str, page_num: int) -> list[dict]:
        """
        Fetch page with chain_slug fallback: try each variant until first 200.
        base_url_template should have {chain_slug} placeholder.
        """
        nonlocal scanned_pairs, pages_done
        last_error = None
        
        for cmc_chain in cmc_chain_variants:
            url = base_url_template.format(chain_slug=cmc_chain)
            try:
                doc = http.cmc_get_json(url, timeout=20.0) or {}
                # Validate response structure
                if not _validate_cmc_pairs_doc(doc):
                    print(f"[cmc][validate] unexpected discovery schema; skipping {chain}/{s} page {page_num}")
                    continue
                
                # Success - process data
                data = doc.get("data") or doc.get("result") or doc.get("items") or []
                items: list[dict] = []
                seen: set[str] = set()
                for pool in data:
                    pool_id, base_tok, quote_tok, liquidity, tx24h, pool_created_at = _extract_common_fields(pool)
                    if not pool_id or pool_id in seen:
                        continue
                    seen.add(pool_id)
                    scanned_pairs += 1
                    ok, token_side, native_side = is_token_native_pair(chain, base_tok, quote_tok)
                    if not ok:
                        continue
                    if not is_base_token_acceptable(chain, token_side):
                        continue
                    if not pool_data_filters(liquidity, cfg.liquidity_min, cfg.liquidity_max, tx24h, cfg.tx24h_max):
                        continue
                    
                    # Extract volume for sorting (if available)
                    volume_24h = 0.0
                    try:
                        volume_24h = float(pool.get("volume_24h_quote") or pool.get("volume_24h") or 0.0)
                    except Exception:
                        pass
                    
                    # Extract listed_at for sorting (if available)
                    listed_at = pool.get("listed_at") or pool_created_at or ""
                    
                    items.append(
                        {
                            "chain": chain,
                            "pool": pool_id,
                            "url": _cmc_pool_url_hint(pool_id),
                            "baseSymbol": (token_side.get("symbol") or ""),
                            "baseAddr": (token_side.get("address") or ""),
                            "quoteSymbol": (native_side.get("symbol") or ""),
                            "quoteAddr": (native_side.get("address") or ""),
                            "liquidity": float(liquidity or 0.0),
                            "tx24h": int(tx24h or 0),
                            "pool_created_at": pool_created_at or "",
                            "volume_24h": volume_24h,
                            "listed_at": listed_at,
                        }
                    )
                pages_done += 1
                return items
                
            except Exception as e:
                last_error = e
                # Check if it's a 400 error - if so, try next variant
                if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                    if e.response.status_code == 400:
                        print(f"[{chain}] CMC {s} 400 with chain_slug={cmc_chain}, trying next variant...")
                        continue
                # For other errors, log and try next variant
                print(f"[{chain}] CMC {s} error with chain_slug={cmc_chain}: {e}")
                continue
        
        # All variants failed
        if last_error:
            print(f"[{chain}] CMC {s} all chain_slug variants failed: {last_error}")
        pages_done += 1
        return []

    if s in {"new", "trending", "pools", "all"}:
        # CMC DEX v4: removed category parameter
        # Fetch all pools, then sort locally based on source type
        for page in range(start_page, max(start_page, 1) + max(0, page_limit)):
            url_template = f"{cfg.cmc_dex_base}/spot-pairs/latest?chain_slug={{chain_slug}}&page={page}&limit={cfg.cmc_page_size}"
            items = _fetch_page_with_fallback(url_template, page)
            if items:
                out.extend(items)
    elif s == "dexes":
        # CMC DEX v4: list dexes for chain, then fetch pairs per dex
        dex_ids: list[str] = []
        for cmc_chain in cmc_chain_variants:
            dexes_url = f"{cfg.cmc_dex_base}/dexes?chain_slug={cmc_chain}"
            try:
                doc = http.cmc_get_json(dexes_url, timeout=20.0) or {}
                dex_items = doc.get("data") or doc.get("result") or []
                if dex_items:
                    for d in dex_items:
                        _id = (d.get("id") or d.get("dex_id") or d.get("slug") or "").strip()
                        if _id:
                            dex_ids.append(_id)
                    break  # Success, stop trying variants
            except Exception as e:
                print(f"[{chain}] CMC dexes list error with chain_slug={cmc_chain}: {e}")
                continue
        
        # Fetch pairs per dex (without category)
        for dex_id in dex_ids:
            for page in range(start_page, max(start_page, 1) + max(0, page_limit)):
                url_template = f"{cfg.cmc_dex_base}/spot-pairs/latest?chain_slug={{chain_slug}}&dex_id={dex_id}&page={page}&limit={cfg.cmc_page_size}"
                items = _fetch_page_with_fallback(url_template, page)
                if items:
                    out.extend(items)
    else:
        # Unknown source - treat as general pools
        for page in range(start_page, max(start_page, 1) + max(0, page_limit)):
            url_template = f"{cfg.cmc_dex_base}/spot-pairs/latest?chain_slug={{chain_slug}}&page={page}&limit={cfg.cmc_page_size}"
            items = _fetch_page_with_fallback(url_template, page)
            if items:
                out.extend(items)

    # Local sorting based on source type (since category param is removed)
    if s == "new":
        # Sort by listed_at / pool_created_at descending (newest first)
        out.sort(key=lambda x: x.get("listed_at") or x.get("pool_created_at") or "", reverse=True)
    elif s == "trending":
        # Sort by volume_24h descending (highest volume first)
        out.sort(key=lambda x: float(x.get("volume_24h") or 0.0), reverse=True)
    # else: "all" or other sources - keep as returned by API

    # de-duplicate by pool id
    dedup: Dict[str, dict] = {}
    for it in out:
        pid = it.get("pool")
        if pid and pid not in dedup:
            dedup[pid] = it
    return list(dedup.values()), {"pages_done": pages_done, "scanned_pairs": scanned_pairs}


def cmc_discover_candidates(
    cfg: Config,
    http: HttpClient,
    storage,
    chain: str,
    *,
    cycle_idx: int,
) -> tuple[list[dict], dict[str, int]]:
    sources = cfg.cmc_sources_list or ["new"]
    if not sources:
        sources = ["new"]
    # rotate sources if enabled: pick exactly one for this cycle
    if cfg.cmc_rotate_sources:
        idx = (max(0, cycle_idx - 1)) % len(sources)
        chosen_sources = [sources[idx]]
    else:
        chosen_sources = sources

    pages_planned = 0
    pages_done_total = 0
    scanned_pairs_total = 0
    all_items: list[dict] = []
    with storage.get_conn() as conn:
        for source in chosen_sources:
            start_page = storage.get_progress(conn, chain, source)
            limit = cfg.cmc_dex_pages_per_chain if source.strip().lower() == "dexes" else cfg.cmc_pages_per_chain
            items, stats = cmc_discover_by_source(cfg, http, chain, source, start_page, limit)
            all_items.extend(items)
            pages_done_total += int(stats.get("pages_done", 0))
            scanned_pairs_total += int(stats.get("scanned_pairs", 0))
            pages_planned += int(limit)
            # bump progress cursor for next cycle
            storage.bump_progress(conn, chain, source, start_page + max(1, limit))

    percent = (100.0 * pages_done_total / float(pages_planned)) if pages_planned > 0 else 100.0
    print(
        f"[discover][{chain}] pages: {pages_done_total}/{pages_planned} ({percent:.0f}%), "
        f"candidates: {len(all_items)}, scanned: {scanned_pairs_total}"
    )
    return all_items, {"pages_planned": pages_planned, "pages_done": pages_done_total, "scanned_pairs": scanned_pairs_total, "sources_used": len(chosen_sources)}


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
