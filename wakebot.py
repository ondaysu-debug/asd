# wakebot.py
import os, time, json, sqlite3, requests, threading, random
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter, Retry
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque

# ------------- .env -------------
load_dotenv(override=True)

def as_bool(val, default=False):
    if val is None: return default
    return str(val).strip().lower() in {"1","true","yes","on"}

# ------------- CONFIG -------------
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID   = os.getenv("TG_CHAT_ID", "")

DEXSCREENER_BASE = os.getenv("DEXSCREENER_BASE", "https://api.dexscreener.com/latest/dex")
GECKO_BASE       = os.getenv("GECKO_BASE",       "https://api.geckoterminal.com/api/v2")

# фильтры кандидатов
MARKET_CAP_MIN = float(os.getenv("MARKET_CAP_MIN", "50000"))
MARKET_CAP_MAX = float(os.getenv("MARKET_CAP_MAX", "800000"))
TX24H_MAX      = int(os.getenv("TX24H_MAX", "2000"))

# сети
CHAINS = [c.strip().lower() for c in os.getenv("CHAINS","base,solana,ethereum").split(",") if c.strip()]

# цикл/алерты
COOLDOWN_MIN        = int(os.getenv("COOLDOWN_MIN","30"))
LOOP_SECONDS        = int(os.getenv("LOOP_SECONDS","60"))
CHAIN_SCAN_WORKERS  = max(1, int(os.getenv("CHAIN_SCAN_WORKERS", "4")))
MAX_CYCLES          = max(0, int(os.getenv("MAX_CYCLES", "0")))
ALERT_FETCH_WORKERS = max(1, int(os.getenv("ALERT_FETCH_WORKERS", "8")))

# лог кандидатов
SAVE_CANDIDATES = as_bool(os.getenv("SAVE_CANDIDATES","true"))
CANDIDATES_PATH = Path(os.getenv("CANDIDATES_PATH","candidates.jsonl")).expanduser()

# охват поиска
SCAN_BY_DEX              = as_bool(os.getenv("SCAN_BY_DEX","true"))
FALLBACK_BUCKETED_SEARCH = as_bool(os.getenv("FALLBACK_BUCKETED_SEARCH","true"))
BUCKET_ALPHABET          = os.getenv("BUCKET_ALPHABET","abcdefghijklmnopqrstuvwxyz0123456789")
USE_TWO_CHAR_BUCKETS     = as_bool(os.getenv("USE_TWO_CHAR_BUCKETS","true"))
MAX_BUCKETS_PER_CHAIN    = int(os.getenv("MAX_BUCKETS_PER_CHAIN","1200"))
BUCKET_DELAY_SEC         = float(os.getenv("BUCKET_DELAY_SEC","0.01"))
MAX_PAIRS_PER_DEX        = int(os.getenv("MAX_PAIRS_PER_DEX","5000"))
BUCKET_SEARCH_TARGET     = int(os.getenv("BUCKET_SEARCH_TARGET","0"))
BUCKET_SEARCH_WORKERS    = max(1, int(os.getenv("BUCKET_SEARCH_WORKERS", "32")))
BUCKET_RETRY_LIMIT       = max(0, int(os.getenv("BUCKET_RETRY_LIMIT", "2")))

GECKO_TTL_SEC = int(os.getenv("GECKO_TTL_SEC", "60"))

# какие DEX-ы сканировать
DEXES_BY_CHAIN = {
    "solana":   ["raydium", "orca", "raydium-clmm", "meteora"],
    "base":     [
        "aerodrome", "uniswap-v3", "uniswap-v2", "sushiswap", "pancakeswap-v3",
        "alienbase", "baseswap", "thruster", "sushiswap-v3"
    ],
    "ethereum": [
        "uniswap", "uniswap-v2", "uniswap-v3", "sushiswap", "pancakeswap-v3",
        "balancer-v2", "maverick"
    ],
}

# БД
DB_PATH = Path(os.getenv("DB_PATH","wake_state.sqlite")).expanduser()

# мейджоры/нативки (не хотим как baseToken)
MAJOR_BASE_SYMBOLS = {
    "USDC","USDT","DAI","WBTC","BTC","TETHER","CIRCLE",
    "ETH","WETH","ETHEREUM","SOL","SOLANA","BASE","STETH","WSTETH","USDCE","USDTE"
}

# Нормализованные адреса (lower для EVM)
NATIVE_ADDR = {
    "base":     {"0x4200000000000000000000000000000000000006"},               # WETH (Base)
    "ethereum": {"0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"},               # WETH (ETH)
    "solana":   {"So11111111111111111111111111111111111111112"},              # SOL (не lower)
}
NATIVE_SYMBOLS = {
    "base":     {"BASE","ETH","WETH","ETHEREUM"},
    "ethereum": {"ETH","WETH","ETHEREUM"},
    "solana":   {"SOL","SOLANA"},
}

# ------------- HTTP SESSION -------------
_SESSION_LOCAL = threading.local()
_GECKO_CACHE: dict = {}

def _build_session():
    session = requests.Session()
    session.headers.update({"User-Agent":"wakebot/1.0"})
    adapter = HTTPAdapter(
        pool_connections=128,
        pool_maxsize=128,
        max_retries=Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=[429,500,502,503,504],
            allowed_methods=frozenset(["GET","POST"])
        )
    )
    session.mount("https://", adapter)
    return session

def http_session():
    session = getattr(_SESSION_LOCAL, "session", None)
    if session is None:
        session = _build_session()
        _SESSION_LOCAL.session = session
    return session

# ------------- UTILS -------------
def now_utc(): return datetime.now(timezone.utc)

def nice(x):
    try:
        v = float(x)
        if v>=1_000_000_000: return f"{v/1_000_000_000:.2f}B"
        if v>=1_000_000:     return f"{v/1_000_000:.2f}M"
        if v>=1_000:         return f"{v/1_000:.2f}k"
        return f"{v:.2f}"
    except: return "n/a"

_CANDIDATE_LOG_LOCK = threading.Lock()

def tg_send(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("TG>", text); return
    try:
        http_session().post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text, "disable_web_page_preview": True},
            timeout=12
        )
    except Exception as e:
        print("TG error:", e)

def save_jsonl(path, obj):
    try:
        p = Path(path).expanduser()
        if not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a",encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False)+"\n")
    except Exception as e:
        print("save_jsonl error:", e)

def norm_addr_for_chain(chain, addr):
    if not addr: return ""
    return addr.lower() if chain in ("base","ethereum") else addr

def is_base_ok(base_token: dict, chain: str) -> bool:
    sym  = ((base_token.get("symbol")  or "").strip())
    addr = norm_addr_for_chain(chain, (base_token.get("address") or "").strip())
    if not sym or not addr: return False
    if sym.upper() in MAJOR_BASE_SYMBOLS: return False
    native_set = {norm_addr_for_chain(chain, a) for a in NATIVE_ADDR.get(chain, set())}
    if addr in native_set: return False
    if sym.upper() in NATIVE_SYMBOLS.get(chain, set()): return False
    return True

# ------------- STORAGE -------------
def db_conn():
    if not DB_PATH.parent.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
      CREATE TABLE IF NOT EXISTS state(
        pool TEXT PRIMARY KEY,
        last_alert_ts INTEGER
      )
    """)
    return conn

def get_last_alert_ts(conn, pool):
    cur = conn.execute("SELECT last_alert_ts FROM state WHERE pool= ?", (pool,))
    row = cur.fetchone()
    return row[0] if row else None

def set_last_alert_ts(conn, pool, ts):
    conn.execute("""
      INSERT INTO state(pool,last_alert_ts) VALUES(?,?)
      ON CONFLICT(pool) DO UPDATE SET last_alert_ts=excluded.last_alert_ts
    """, (pool, ts))
    conn.commit()

# ------------- DISCOVERY (DEX + BUCKETS) -------------
def _make_buckets():
    one = list(BUCKET_ALPHABET)
    two = [a + b for a in BUCKET_ALPHABET for b in BUCKET_ALPHABET] if USE_TWO_CHAR_BUCKETS else []
    buckets = (one + two)[:MAX_BUCKETS_PER_CHAIN]
    if not buckets:
        return buckets
    rnd = random.Random()
    rnd.shuffle(buckets)
    return buckets

def _fetch_pairs_by_dex(chain: str, dex_id: str):
    url = f"{DEXSCREENER_BASE}/pairs/{chain}/{dex_id}"
    try:
        r = http_session().get(url, timeout=30)
        r.raise_for_status()
        pairs = (r.json() or {}).get("pairs", []) or []
        if not pairs:
            time.sleep(random.uniform(0.05, 0.15))
        return pairs
    except Exception as e:
        print(f"[{chain}] pairs/{dex_id} error:", e)
        return []

def _bucketed_search(chain: str, native_raw: str):
    acc, seen = [], set()
    buckets = _make_buckets()
    if not buckets:
        return acc

    max_workers = max(1, min(len(buckets), BUCKET_SEARCH_WORKERS))

    def fetch_bucket(bucket):
        if BUCKET_DELAY_SEC > 0:
            time.sleep(random.uniform(0.5, 1.5) * BUCKET_DELAY_SEC)
        url = f"{DEXSCREENER_BASE}/search?q={native_raw}%20{bucket}"
        try:
            r = http_session().get(url, timeout=15)
            r.raise_for_status()
            return (r.json() or {}).get("pairs", []) or []
        except Exception:
            return None

    queue = deque((bucket, 0) for bucket in buckets)
    futures = {}

    def submit(pool, bucket, attempt):
        futures[pool.submit(fetch_bucket, bucket)] = (bucket, attempt)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        while queue and len(futures) < max_workers:
            submit(pool, *queue.popleft())

        while futures:
            for fut in as_completed(list(futures)):
                bucket, attempt = futures.pop(fut)
                pairs = fut.result()

                if not pairs:
                    if attempt + 1 <= BUCKET_RETRY_LIMIT:
                        queue.append((bucket, attempt + 1))
                else:
                    for p in pairs:
                        if (p.get("chainId") or "").lower() != chain.lower():
                            continue
                        pid = p.get("pairAddress")
                        if not pid or pid in seen:
                            continue
                        seen.add(pid)
                        acc.append(p)

                if BUCKET_SEARCH_TARGET > 0 and len(acc) >= BUCKET_SEARCH_TARGET:
                    for pending in list(futures):
                        pending.cancel()
                    futures.clear()
                    queue.clear()
                    break

                if queue:
                    submit(pool, *queue.popleft())
            else:
                continue
            break

    return acc

def ds_search_native_pairs(chain: str):
    """
    1) соберём пары у ряда DEX'ов (широкий охват),
    2) если мало — добавим bucketed /search по адресу нативки,
    3) отфильтруем до TOKEN/native и по критериям (FDV min/max, TX24H).
    Возврат: (candidates, scanned_count)
    """
    native_raw = next(iter(NATIVE_ADDR.get(chain, set())), None)
    if not native_raw:
        print(f"[{chain}] no native address configured"); return [], 0

    all_pairs, scanned = [], 0

    if SCAN_BY_DEX:
        dexes = DEXES_BY_CHAIN.get(chain, [])
        if dexes:
            max_workers = min(len(dexes), 8)
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_fetch_pairs_by_dex, chain, dex_id): dex_id for dex_id in dexes}
                for fut in as_completed(futures):
                    pairs = fut.result()
                    if not pairs:
                        continue
                    limited = pairs[:MAX_PAIRS_PER_DEX]
                    scanned += len(limited)
                    all_pairs.extend(limited)

    need_bucket_search = False
    if FALLBACK_BUCKETED_SEARCH:
        if BUCKET_SEARCH_TARGET <= 0:
            need_bucket_search = True
        else:
            need_bucket_search = scanned < max(200, BUCKET_SEARCH_TARGET)

    if need_bucket_search:
        buckets = _bucketed_search(chain, native_raw)
        scanned += len(buckets); all_pairs.extend(buckets)

    if scanned == 0:
        print(f"[{chain}] nothing fetched (DEX + fallback)."); return [], 0

    native_cmp = norm_addr_for_chain(chain, native_raw)
    out, skipped_maj, skipped_not_native = [], 0, 0
    seen_pools = set()

    for p in all_pairs:
        if (p.get("chainId") or "").lower() != chain.lower(): continue
        pool_addr = p.get("pairAddress")
        if not pool_addr or pool_addr in seen_pools: continue
        seen_pools.add(pool_addr)

        baseTok  = p.get("baseToken")  or {}
        quoteTok = p.get("quoteToken") or {}
        bAddr = norm_addr_for_chain(chain, baseTok.get("address")  or "")
        qAddr = norm_addr_for_chain(chain, quoteTok.get("address") or "")

        # привести к TOKEN/native
        if qAddr == native_cmp and bAddr != native_cmp:
            norm_baseTok, norm_quoteTok = baseTok, quoteTok
        elif bAddr == native_cmp and qAddr != native_cmp:
            norm_baseTok, norm_quoteTok = quoteTok, baseTok
        else:
            skipped_not_native += 1
            continue

        # отсечь мейджоры/мимики/нативки
        if not is_base_ok(norm_baseTok, chain):
            skipped_maj += 1
            continue

        # фильтры по рынку
        fdv = float((p.get("fdv") or p.get("marketCap") or 0) or 0)
        if not (MARKET_CAP_MIN <= fdv <= MARKET_CAP_MAX):
            continue

        txns24 = (p.get("txns") or {}).get("h24", {}) or {}
        tx24h  = int((txns24.get("buys") or 0) + (txns24.get("sells") or 0))
        if tx24h > TX24H_MAX:
            continue

        volume   = (p.get("volume") or {})
        vol5m    = float((volume.get("m5"))  or 0.0)
        vol1h    = float((volume.get("h1"))  or 0.0)
        vol24h   = float((volume.get("h24")) or 0.0)
        vol48h   = float(volume.get("h48") or 0.0)
        if vol48h <= 0 and vol24h > 0:
            vol48h = vol24h * 2.0
        txns5m  = (p.get("txns") or {}).get("m5", {}) or {}
        tx5m    = int((txns5m.get("buys") or 0) + (txns5m.get("sells") or 0))

        cand = {
            "chain":       chain,
            "pool":        pool_addr,
            "url":         p.get("url") or f"https://dexscreener.com/{chain}/{pool_addr}",
            "baseSymbol":  (norm_baseTok.get("symbol")  or ""),
            "baseAddr":    (norm_baseTok.get("address") or ""),
            "quoteSymbol": (norm_quoteTok.get("symbol") or ""),
            "quoteAddr":   (norm_quoteTok.get("address") or ""),
            "fdv":         fdv,
            "tx24h":       tx24h,
            "vol5m_ds":    vol5m,
            "vol1h_ds":    vol1h,
            "vol24h_ds":   vol24h,
            "vol48h_ds":   vol48h,
            "tx5m_ds":     tx5m
        }
        dump_candidate(cand)
        out.append(cand)

    print(f"[{chain}] scanned: {scanned}, candidates: {len(out)} "
          f"(skipped majors/mimics: {skipped_maj}, non TOKEN/native: {skipped_not_native})")
    return out, scanned

# ------------- LOGGING CANDIDATES -------------
def dump_candidate(rec: dict):
    if not SAVE_CANDIDATES: return
    out = dict(rec); out["ts"] = now_utc().isoformat()
    with _CANDIDATE_LOG_LOCK:
        save_jsonl(CANDIDATES_PATH, out)

# ------------- GECKO (vol1h/vol48h/tx1h) -------------
def fetch_gecko_for_pool(chain, pool_addr):
    key = (chain, pool_addr)
    now_ts = time.time()
    cached = _GECKO_CACHE.get(key)
    if cached and now_ts - cached[0] < GECKO_TTL_SEC:
        return cached[1]

    gecko_chain = "ethereum" if chain == "ethereum" else chain
    url = f"{GECKO_BASE}/networks/{gecko_chain}/pools/{pool_addr}"
    try:
        r = http_session().get(url, timeout=20)
        if r.status_code == 404:
            data = (0.0, 0, 0.0)
        else:
            r.raise_for_status()
            attributes = (r.json() or {}).get("data", {}).get("attributes", {}) or {}
            volume_usd = attributes.get("volume_usd") or {}
            transactions = attributes.get("transactions") or {}
            tx_h1 = transactions.get("h1") or {}
            vol1h = float(volume_usd.get("h1") or 0)
            vol48h = float(volume_usd.get("h48") or volume_usd.get("d2") or 0)
            if vol48h <= 0:
                vol48h = float(volume_usd.get("h24") or 0) * 2.0
            data = (
                vol1h,
                int((tx_h1.get("buys") or 0) + (tx_h1.get("sells") or 0)),
                vol48h,
            )
    except Exception:
        data = (0.0, 0, 0.0)

    _GECKO_CACHE[key] = (now_ts, data)
    return data


def _ds_precheck(meta: dict) -> bool:
    v1 = float(meta.get("vol1h_ds") or 0.0)
    v48 = float(meta.get("vol48h_ds") or 0.0)
    prev48 = max(v48 - v1, 0.0)
    return v1 > 0 and v1 > prev48

# ------------- TRIGGER (1h > prev48h) -------------
def maybe_alert(conn, meta):
    pool  = meta["pool"]
    chain = meta["chain"]

    # кулдаун
    last = get_last_alert_ts(conn, pool)
    if last and now_utc() - datetime.fromtimestamp(last, tz=timezone.utc) < timedelta(minutes=COOLDOWN_MIN):
        return

    # окна: Gecko → fallback на DS
    cached_gecko = meta.get("_gecko_data")
    if cached_gecko is None:
        cached_gecko = fetch_gecko_for_pool(chain, pool)
    vol1h, tx1h, vol48h = cached_gecko
    gecko_failed = (vol1h, tx1h, vol48h) == (0.0, 0, 0.0)
    ds_vol1h = float(meta.get("vol1h_ds", 0.0))
    ds_vol48h = float(meta.get("vol48h_ds", 0.0))
    if gecko_failed:
        vol1h = ds_vol1h
        vol48h = ds_vol48h
        if vol1h <= 0 and vol48h <= 0:
            print(f"[{chain}] skip alert for {pool}: no volume data from Gecko or DexScreener")
            return
        if vol48h <= 0:
            print(f"[{chain}] skip alert for {pool}: Gecko unavailable and DexScreener 48h volume is zero")
            return

    # "предыдущие 48ч" = 48h без текущего часа
    prev48 = max(vol48h - vol1h, 0.0)

    # условие: текущий час больше всех предыдущих 48 часов
    if vol1h <= 0 or vol1h <= prev48:
        return

    set_last_alert_ts(conn, pool, int(now_utc().timestamp()))
    ratio = (vol1h / prev48) if prev48 > 0 else float('inf')

    source_tag = "Gecko" if not gecko_failed else "DexScreener"

    text = (
        f"🚨 WAKE-UP ({chain.capitalize()})\n"
        f"Pool: {pool}\n"
        f"Token: {meta.get('baseSymbol') or 'n/a'}\n"
        f"Contract: `{meta.get('baseAddr') or 'n/a'}`\n"
        f"FDV: ${nice(meta.get('fdv'))}\n\n"
        f"1h Vol: ${nice(vol1h)} ({source_tag})\n"
        f"Prev 48h Vol (excl. current 1h): ${nice(prev48)}\n"
        f"Ratio 1h/prev48h: {ratio:.2f}x\n"
        f"Link: {meta.get('url')}"
    )
    tg_send(text)
    print("Alert:", chain, pool, "vol1h > prev48h")

# ------------- MAIN LOOP -------------
def main():
    print(f"Wake-up bot started. Chains: {', '.join(CHAINS)}")
    print(f"Save candidates: {SAVE_CANDIDATES} -> {CANDIDATES_PATH}")
    if MAX_CYCLES:
        print(f"Max cycles: {MAX_CYCLES}")
    conn = db_conn()

    cycle_idx = 0
    while True:
        cycle_idx += 1
        cycle_started = time.monotonic()
        total_scanned = 0
        total_cands   = 0

        chain_results = []
        if CHAINS:
            max_workers = min(len(CHAINS), CHAIN_SCAN_WORKERS)
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_to_chain = {pool.submit(ds_search_native_pairs, chain): chain for chain in CHAINS}
                for fut in as_completed(future_to_chain):
                    chain_name = future_to_chain[fut]
                    try:
                        cands, scanned = fut.result()
                        chain_results.append((chain_name, cands, scanned))
                    except Exception as e:
                        print(f"[{chain_name}] error:", e)

        # сохранить порядок CHAINS в выводе
        if len(chain_results) > 1:
            order = {c: i for i, c in enumerate(CHAINS)}
            chain_results.sort(key=lambda x: order.get(x[0], 0))

        aggregated = []
        for chain_name, cands, scanned in chain_results:
            total_scanned += scanned
            total_cands   += len(cands)
            aggregated.extend(cands)

        prechecked = [meta for meta in aggregated if _ds_precheck(meta)]

        if prechecked:
            workers = min(len(prechecked), ALERT_FETCH_WORKERS)
            if workers:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    future_map = {pool.submit(fetch_gecko_for_pool, meta["chain"], meta["pool"]): meta for meta in prechecked}
                    for fut in as_completed(future_map):
                        meta = future_map[fut]
                        try:
                            meta["_gecko_data"] = fut.result()
                        except Exception:
                            meta["_gecko_data"] = (0.0, 0, 0.0)

        for meta in prechecked:
            maybe_alert(conn, meta)

        elapsed = time.monotonic() - cycle_started
        print(f"[cycle] scanned total: {total_scanned}, candidates total: {total_cands}, took {elapsed:.2f}s")
        sleep_for = max(0.0, LOOP_SECONDS - elapsed)
        if sleep_for:
            time.sleep(sleep_for)

        if MAX_CYCLES and cycle_idx >= MAX_CYCLES:
            print(f"[cycle] reached MAX_CYCLES={MAX_CYCLES}, stopping loop")
            break

if __name__ == "__main__":
    main()
