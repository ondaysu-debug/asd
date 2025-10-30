from __future__ import annotations

from typing import Dict, List, Tuple

from .config import Config
from .filters import is_base_token_acceptable, is_token_native_pair, pool_data_filters
from .cmc import _validate_cmc_pairs_doc
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


# ---------------- CMC DEX discovery ----------------

def _cmc_chain_slug(cfg: Config, chain: str) -> str:
    # Prefer configured slug mapping; fallback to the input as-is
    s = (chain or "").strip().lower()
    return (cfg.chain_slugs or {}).get(s, s)


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
    cmc_chain = _cmc_chain_slug(cfg, chain)
    s = (source or "").strip().lower()
    out: list[dict] = []
    scanned_pairs = 0
    pages_done = 0
    invalid_pages = 0

    def _fetch_page(url: str) -> list[dict]:
        nonlocal scanned_pairs, pages_done
        try:
            doc = http.cmc_get_json(url, timeout=20.0) or {}
            if not _validate_cmc_pairs_doc(doc):
                print(f"[cmc][validate] unexpected discovery schema; skipping page {page}")
                pages_done += 1
                invalid_pages += 1
                return []
        except Exception as e:
            print(f"[{chain}] CMC {s} error: {e}")
            pages_done += 1
            return []
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
                }
            )
        pages_done += 1
        return items

    if s in {"new", "trending", "pools"}:
        for page in range(start_page, max(start_page, 1) + max(0, page_limit)):
            # Note: CMC public doc shows v4 path like /v4/dex/spot-pairs/latest with params.
            # Our production endpoint uses dexer/v3 style: /{chain}/pools[/new|/trending].
            # Adapt here if your account exposes a different schema.
            url = f"{cfg.cmc_dex_base}/{cmc_chain}/pools/{'new' if s=='new' else 'trending' if s=='trending' else ''}"
            if url.endswith("/"):
                url = url[:-1]
            url = f"{url}?page={page}&page_size={cfg.cmc_page_size}"
            items = _fetch_page(url)
            if items:
                out.extend(items)
    elif s == "dexes":
        # list dexes
        # In v4 doc this may be available under /v4/dex/dexes; here we use dexer/v3 style
        dexes_url = f"{cfg.cmc_dex_base}/{cmc_chain}/dexes"
        try:
            doc = http.cmc_get_json(dexes_url, timeout=20.0) or {}
            dex_items = doc.get("data") or doc.get("result") or []
        except Exception:
            dex_items = []
        dex_ids: list[str] = []
        for d in dex_items:
            _id = (d.get("id") or d.get("dex_id") or d.get("slug") or "").strip()
            if _id:
                dex_ids.append(_id)
        for dex_id in dex_ids:
            for page in range(start_page, max(start_page, 1) + max(0, page_limit)):
                url = f"{cfg.cmc_dex_base}/{cmc_chain}/dexes/{dex_id}/pools?page={page}&page_size={cfg.cmc_page_size}"
                items = _fetch_page(url)
                if items:
                    out.extend(items)
    else:
        # treat as pools
        for page in range(start_page, max(start_page, 1) + max(0, page_limit)):
            url = f"{cfg.cmc_dex_base}/{cmc_chain}/pools?page={page}&page_size={cfg.cmc_page_size}"
            items = _fetch_page(url)
            if items:
                out.extend(items)

    # de-duplicate by pool id
    dedup: Dict[str, dict] = {}
    for it in out:
        pid = it.get("pool")
        if pid and pid not in dedup:
            dedup[pid] = it
    return list(dedup.values()), {"pages_done": pages_done, "scanned_pairs": scanned_pairs, "validation_errors": invalid_pages}


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
