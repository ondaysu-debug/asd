## WakeBot - Crypto Token Alert Bot

Reliable TOKEN/native discovery and alerts using CoinMarketCap DEX API (primary) with optional GeckoTerminal OHLCV fallback. Scans Base, Solana, Ethereum, and BSC, filters noise, fetches precise OHLCV windows, and sends Telegram notifications for REVIVAL signals.

### Features
- **Discovery (CMC DEX):**
  - Sources: `new`, `trending`, raw `pools`, and `dexes/{dex}/pools`
  - Rotation across sources per cycle with `CMC_ROTATE_SOURCES=true`
  - Normalizes to TOKEN/native pairs (WETH on EVM, SOL on Solana)
- **Filtering:**
  - Normalize addresses by chain
  - Convert to TOKEN/native (WETH on EVM, SOL on Solana)
  - Exclude majors/mimics by symbol/addresses
  - Filter by liquidity range and `tx24h` max
- **Metrics (CMC DEX OHLCV 25h):**
  - Fetch 25 hourly candles per pool (`limit=25`)
  - Derive `vol1h` (last hour) and `prev24h` (24 hours before last)
  - TTL cache for OHLCV results (configurable); optional GT fallback
- **Alerts:**
  - REVIVAL rule: age >= `REVIVAL_MIN_AGE_DAYS`, `now_24h` >= min, `prev_week` <= max, and `now_24h / prev_week` >= `REVIVAL_RATIO_MIN` (optional `REVIVAL_USE_LAST_HOURS`)
  - Per-pool cooldown in SQLite
  - Telegram notifications with Markdown escaping for dynamic fields
- **Rate limiting (GeckoTerminal):**
  - Global token-bucket with adaptive RPS control and max concurrency
  - Dynamic per-cycle HTTP budget with 429 penalty awareness
  - Respects `Retry-After` (seconds or HTTP-date) with configurable cap
  - 5xx retries (2 attempts) with small backoff
- **Concurrency:**
  - Multi-threaded chain scanning and alert fetch
- **Logging:**
  - Candidates logged to JSONL with timestamps
- **Resilience:**
  - Non-fatal HTTP/parse errors; skips and continues

### Requirements
- Python 3.10+
- Only standard library + `requests`, `python-dotenv` (and `pytest` for tests)

### Installation
```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` as needed.

### Running
- One cycle (for cron/k8s):
```bash
python -m wakebot.main --once
```
- Continuous loop:
```bash
python -m wakebot.main
```

You can also use the package entrypoint directly:
```bash
python -m wakebot --once   # single cycle
python -m wakebot          # continuous
```

### Configuration (.env)
See `.env.example` for all variables. Key ones and defaults:

| Variable | Default | Notes |
|---|---|---|
| `CMC_DEX_BASE` | `https://api.coinmarketcap.com/dexer/v3` | CMC DEX API base |
| `CMC_DEX_BASE_ALT` | `https://pro-api.coinmarketcap.com/dexer/v3` | Alt base for retry |
| `CMC_API_KEY` | `` | API key (optional) |
| `CMC_CALLS_PER_MIN` | `28` | HTTP budget per minute |
| `CMC_RETRY_AFTER_CAP_S` | `3` | Cap for Retry-After |
| `CMC_SOURCES` | `new,trending,pools,dexes` | Discovery sources |
| `CMC_ROTATE_SOURCES` | `true` | Rotate one source per cycle |
| `CMC_PAGES_PER_CHAIN` | `2` | Pages per source per chain |
| `CMC_DEX_PAGES_PER_CHAIN` | `1` | Pages per dex per chain |
| `CMC_PAGE_SIZE` | `100` | Items per page |
| `ALLOW_GT_OHLCV_FALLBACK` | `false` | Use GT OHLCV if CMC empty |
| `GECKO_BASE` | `https://api.geckoterminal.com/api/v2` | GT base (fallback only) |
| `LIQUIDITY_MIN` | `50000` | USD |
| `LIQUIDITY_MAX` | `800000` | USD |
| `TX24H_MAX` | `2000` | Buys + sells in 24h |
| `GECKO_TTL_SEC` | `60` | TTL for OHLCV cache |
| `MAX_OHLCV_PROBES_CAP` | `30` | Max per-cycle OHLCV probes |
| `GECKO_SAFETY_BUDGET` | `4` | Reserve HTTP calls per cycle |
| `MIN_OHLCV_PROBES` | `3` | Minimum probes if budget allows |
| `ALERT_RATIO_MIN` | `1.0` | Optional classic 1h vs prev48 rule |
| `SEEN_TTL_MIN` | `15` | Skip OHLCV for seen pools (minutes) |
| `COOLDOWN_MIN` | `30` | Per-pool alert cooldown |
| `LOOP_SECONDS` | `60` | Target loop duration |
| `CHAIN_SCAN_WORKERS` | `4` | Parallel chains for discovery |
| `ALERT_FETCH_WORKERS` | `8` | Parallel alert checks/sends |
| `TG_PARSE_MODE` | `Markdown` | Telegram parse mode |
| `CHAINS` | `base,solana,ethereum,bsc` | Supported: `ethereum`, `base`, `solana`, `bsc` |

Typical per-loop budget: planned pages + OHLCV probes (keep under `CMC_CALLS_PER_MIN`).

Example `.env` snippet:

```bash
# --- CMC DEX API ---
CMC_DEX_BASE=https://api.coinmarketcap.com/dexer/v3
CMC_DEX_BASE_ALT=https://pro-api.coinmarketcap.com/dexer/v3
CMC_API_KEY=

# limits and cache
CMC_CALLS_PER_MIN=28
CMC_RETRY_AFTER_CAP_S=3
GECKO_BASE=https://api.geckoterminal.com/api/v2
GECKO_TTL_SEC=60

# discovery sources
CMC_SOURCES=new,trending,pools,dexes
CMC_ROTATE_SOURCES=true
CMC_PAGE_SIZE=100
CMC_PAGES_PER_CHAIN=2
CMC_DEX_PAGES_PER_CHAIN=1

# budgets/limiter
MAX_OHLCV_PROBES_CAP=30
MIN_OHLCV_PROBES=3
CMC_SAFETY_BUDGET=4

# pre-check filters
LIQUIDITY_MIN=50000
LIQUIDITY_MAX=800000
TX24H_MAX=2000

# revival / alerts
REVIVAL_MIN_AGE_DAYS=7
MIN_PREV24_USD=1000
ALERT_RATIO_MIN=1.0
SEEN_TTL_MIN=15

# chains
CHAINS=base,solana,ethereum,bsc

# optional GT OHLCV fallback
ALLOW_GT_OHLCV_FALLBACK=false
```

### Tests
Run unit tests:
```bash
pytest -q
```

Coverage includes:
- Address normalization and TOKEN/native determination
- Liquidity/tx filters
- Alert rule and cooldown
- Throttler behavior and adaptive changes
- Gecko TTL cache (no HTTP until TTL expiry)

### Notes
- Primary data source: CoinMarketCap DEX API; optional GeckoTerminal OHLCV fallback
- Works on Windows, macOS, Linux; no POSIX-only dependencies
- No Docker/Poetry required (optional to add later)
