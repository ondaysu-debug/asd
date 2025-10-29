## WakeBot - Crypto Token Alert Bot

Reliable TOKEN/native discovery and alerts using the public GeckoTerminal API only (no Pro). Scans Base, Solana, and Ethereum, filters noise, fetches precise OHLCV windows, and sends Telegram notifications for REVIVAL signals: older pools that were quiet last week but woke up in the last 24h.

### Features
- **Discovery (GeckoTerminal):**
  - Sources: `new_pools`, `trending_pools`, raw `pools`, and `dexes/{dex}/pools`
  - Rotation across sources per cycle with `GECKO_ROTATE_SOURCES=true`
  - Normalizes to TOKEN/native pairs (WETH on EVM, SOL on Solana)
- **Filtering:**
  - Normalize addresses by chain
  - Convert to TOKEN/native (WETH on EVM, SOL on Solana)
  - Exclude majors/mimics by symbol/addresses
  - Filter by liquidity range and `tx24h` max
- **Metrics (GeckoTerminal OHLCV only):**
  - Fetch 193 hourly candles per pool for revival (`/ohlcv/hour?limit=193`)
  - Derive `now_24h` (sum of last 24h) and `prev_week` (sum of 168h before last 24h)
  - TTL cache for OHLCV results (configurable)
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
| `GECKO_BASE` | `https://api.geckoterminal.com/api/v2` | Public GT API base |
| `GECKO_CALLS_PER_MIN` | `28` | Public budget target (< 30/min) |
| `GECKO_RETRY_AFTER_CAP_S` | `3.0` | Max sleep for Retry-After |
| `GECKO_SOURCES` | `new,trending,pools,dexes` | Discovery sources |
| `GECKO_ROTATE_SOURCES` | `true` | Rotate one source per cycle |
| `GECKO_PAGES_PER_CHAIN` | `2` | Pages per source per chain |
| `GECKO_DEX_PAGES_PER_CHAIN` | `1` | Pages per dex per chain |
| `GECKO_PAGE_SIZE` | `100` | Items per page |
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
| `CHAINS` | `base,solana,ethereum` | Supported: `ethereum→eth`, `base`, `solana` |

Typical per-loop budget: pages * sources + OHLCV probes (keep under `GECKO_CALLS_PER_MIN`).

Example `.env` snippet:

```bash
GECKO_BASE=https://api.geckoterminal.com/api/v2
GECKO_CALLS_PER_MIN=28
GECKO_RETRY_AFTER_CAP_S=3.0
GECKO_SOURCES=new,trending,pools,dexes
GECKO_ROTATE_SOURCES=true
GECKO_PAGES_PER_CHAIN=2
GECKO_DEX_PAGES_PER_CHAIN=1
GECKO_PAGE_SIZE=100
LIQUIDITY_MIN=50000
LIQUIDITY_MAX=800000
TX24H_MAX=2000
CHAINS=base,solana,ethereum
GECKO_TTL_SEC=60
MAX_OHLCV_PROBES_CAP=30
GECKO_SAFETY_BUDGET=4
MIN_OHLCV_PROBES=3
ALERT_RATIO_MIN=1.0
SEEN_TTL_MIN=15
COOLDOWN_MIN=30
LOOP_SECONDS=60
CHAIN_SCAN_WORKERS=4
ALERT_FETCH_WORKERS=8
MAX_CYCLES=0
SAVE_CANDIDATES=true
CANDIDATES_PATH=./candidates.jsonl
DB_PATH=wake_state.sqlite
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
- Public GeckoTerminal only; no DexScreener or CoinGecko On-Chain
- Works on Windows, macOS, Linux; no POSIX-only dependencies
- No Docker/Poetry required (optional to add later)
