from __future__ import annotations

import random
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

from .config import Config
from .filters import fdv_tx_filters, is_base_token_acceptable, is_token_native_pair, normalize_address
from .net_http import HttpClient


DEXES_BY_CHAIN: Dict[str, List[str]] = {
    "solana": ["raydium", "orca", "raydium-clmm", "meteora"],
    "base": [
        "aerodrome",
        "uniswap-v3",
        "uniswap-v2",
        "sushiswap",
        "pancakeswap-v3",
        "alienbase",
        "baseswap",
        "thruster",
        "sushiswap-v3",
    ],
    "ethereum": [
        "uniswap",
        "uniswap-v2",
        "uniswap-v3",
        "sushiswap",
        "pancakeswap-v3",
        "balancer-v2",
        "maverick",
    ],
}


def _make_buckets(cfg: Config) -> List[str]:
    one = list(cfg.bucket_alphabet)
    two = [a + b for a in cfg.bucket_alphabet for b in cfg.bucket_alphabet] if cfg.use_two_char_buckets else []
    buckets = (one + two)[: cfg.max_buckets_per_chain]
    rnd = random.Random()
    rnd.shuffle(buckets)
    return buckets


def _fetch_pairs_by_dex(cfg: Config, http: HttpClient, chain: str, dex_id: str) -> List[dict]:
    url = f"{cfg.dexscreener_base}/pairs/{chain}/{dex_id}"
    try:
        doc = http.ds_get_json(url, timeout=30.0)
        return (doc.get("pairs") or [])[: cfg.max_pairs_per_dex]
    except Exception as e:
        print(f"[{chain}] pairs/{dex_id} error: {e}")
        return []


def _bucketed_search(cfg: Config, http: HttpClient, chain: str, native_raw: str) -> List[dict]:
    buckets = _make_buckets(cfg)
    if not buckets:
        return []

    max_workers = max(1, min(len(buckets), cfg.bucket_search_workers))

    def fetch_bucket(bucket: str) -> List[dict] | None:
        if cfg.bucket_delay_sec > 0:
            time.sleep(random.uniform(0.5, 1.5) * cfg.bucket_delay_sec)
        url = f"{cfg.dexscreener_base}/search?q={native_raw}%20{bucket}"
        try:
            doc = http.ds_get_json(url, timeout=15.0)
            return (doc.get("pairs") or [])
        except Exception:
            return None

    queue: deque[tuple[str, int]] = deque((bucket, 0) for bucket in buckets)
    acc: List[dict] = []
    seen: set[str] = set()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        # prime the pool
        while queue and len(futures) < max_workers:
            b, attempt = queue.popleft()
            futures[pool.submit(fetch_bucket, b)] = (b, attempt)

        while futures:
            for fut in as_completed(list(futures)):
                b, attempt = futures.pop(fut)
                pairs = fut.result()
                if not pairs:
                    if attempt + 1 <= cfg.bucket_retry_limit:
                        queue.append((b, attempt + 1))
                else:
                    for p in pairs:
                        if (p.get("chainId") or "").lower() != chain.lower():
                            continue
                        pid = p.get("pairAddress")
                        if not pid or pid in seen:
                            continue
                        seen.add(pid)
                        acc.append(p)

                if cfg.bucket_search_target > 0 and len(acc) >= cfg.bucket_search_target:
                    for pending in list(futures):
                        pending.cancel()
                    futures.clear()
                    queue.clear()
                    break

                if queue:
                    nb, nattempt = queue.popleft()
                    futures[pool.submit(fetch_bucket, nb)] = (nb, nattempt)
            else:
                continue
            break

    return acc


def ds_search_native_pairs(cfg: Config, http: HttpClient, chain: str) -> tuple[list[dict], int]:
    """
    1) Wider coverage via pairs/{chain}/{dex}
    2) If too few, add bucketed /search by native address
    3) Convert to TOKEN/native and apply FDV/tx filters
    Returns (candidates, scanned_count)
    """
    # pick first native address, if any
    from .constants import NATIVE_ADDR

    native_raw = next(iter(NATIVE_ADDR.get(chain, set())), None)
    if not native_raw:
        print(f"[{chain}] no native address configured")
        return [], 0

    scanned = 0
    all_pairs: List[dict] = []

    if cfg.scan_by_dex:
        dexes = DEXES_BY_CHAIN.get(chain, [])
        if dexes:
            max_workers = min(len(dexes), 8)
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_fetch_pairs_by_dex, cfg, http, chain, dex_id): dex_id for dex_id in dexes}
                for fut in as_completed(futures):
                    pairs = fut.result() or []
                    if not pairs:
                        continue
                    scanned += len(pairs)
                    all_pairs.extend(pairs)

    need_bucket_search = False
    if cfg.fallback_bucketed_search:
        if cfg.bucket_search_target <= 0:
            need_bucket_search = True
        else:
            need_bucket_search = scanned < max(200, cfg.bucket_search_target)

    if need_bucket_search:
        buckets = _bucketed_search(cfg, http, chain, native_raw)
        scanned += len(buckets)
        all_pairs.extend(buckets)

    if scanned == 0:
        print(f"[{chain}] nothing fetched (DEX + fallback).")
        return [], 0

    native_cmp = normalize_address(chain, native_raw)
    out: List[dict] = []
    skipped_maj = 0
    skipped_not_native = 0
    seen_pools: set[str] = set()

    for p in all_pairs:
        if (p.get("chainId") or "").lower() != chain.lower():
            continue
        pool_addr = p.get("pairAddress")
        if not pool_addr or pool_addr in seen_pools:
            continue
        seen_pools.add(pool_addr)

        base_tok = p.get("baseToken") or {}
        quote_tok = p.get("quoteToken") or {}

        ok, token_side, native_side = is_token_native_pair(chain, base_tok, quote_tok)
        if not ok:
            skipped_not_native += 1
            continue

        if not is_base_token_acceptable(chain, token_side):
            skipped_maj += 1
            continue

        fdv = float((p.get("fdv") or p.get("marketCap") or 0) or 0)
        txns24 = (p.get("txns") or {}).get("h24", {}) or {}
        tx24h = int((txns24.get("buys") or 0) + (txns24.get("sells") or 0))
        if not fdv_tx_filters(fdv, cfg.market_cap_min, cfg.market_cap_max, tx24h, cfg.tx24h_max):
            continue

        volume = (p.get("volume") or {})
        vol5m = float(volume.get("m5") or 0.0)
        vol1h = float(volume.get("h1") or 0.0)
        vol24h = float(volume.get("h24") or 0.0)
        vol48h = float(volume.get("h48") or 0.0)
        if vol48h <= 0 and vol24h > 0:
            vol48h = vol24h * 2.0
        txns5m = (p.get("txns") or {}).get("m5", {}) or {}
        tx5m = int((txns5m.get("buys") or 0) + (txns5m.get("sells") or 0))

        out.append(
            {
                "chain": chain,
                "pool": pool_addr,
                "url": p.get("url") or f"https://dexscreener.com/{chain}/{pool_addr}",
                "baseSymbol": (token_side.get("symbol") or ""),
                "baseAddr": (token_side.get("address") or ""),
                "quoteSymbol": (native_side.get("symbol") or ""),
                "quoteAddr": (native_side.get("address") or ""),
                "fdv": fdv,
                "tx24h": tx24h,
                "vol5m_ds": vol5m,
                "vol1h_ds": vol1h,
                "vol24h_ds": vol24h,
                "vol48h_ds": vol48h,
                "tx5m_ds": tx5m,
            }
        )

    print(
        f"[{chain}] scanned: {scanned}, candidates: {len(out)} "
        f"(skipped majors/mimics: {skipped_maj}, non TOKEN/native: {skipped_not_native})"
    )

    return out, scanned
