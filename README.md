## WakeBot - Crypto Token Alert Bot

A reliable bot that discovers TOKEN/native pools across Base, Solana, and Ethereum using Dexscreener, fetches on-chain metrics from CoinGecko On-Chain (public REST), and triggers Telegram alerts when the last 1h volume exceeds the previous 48h volume (excluding the current hour).

### Features
- **Discovery:**
  - Scan Dexscreener `pairs/{chain}/{dex}` for broad coverage
  - Fallback bucketed search using `/search?q=<native_addr> <bucket>`
  - Configurable DEX lists, buckets, retries, and breadth
- **Filtering:**
  - Normalize addresses by chain
  - Convert to TOKEN/native (WETH on EVM, SOL on Solana)
  - Exclude majors/mimics by symbol/addresses
  - Filter by FDV range and tx24h max
- **Metrics:**
  - Pull `volume_usd.h1/h48` and `transactions.h1` from CoinGecko On-Chain (REST)
  - TTL cache (thread-safe)
  - Fallback on Dexscreener volumes if CoinGecko REST returns no data (no alert if vol48h == 0)
- **Alerts:**
  - Rule: `vol1h > max(vol48h - vol1h, 0)`
  - Per-pool cooldown in SQLite
  - Telegram notifications (Markdown)
- **Rate limiting (Dexscreener):**
  - Global token-bucket (tokens/sec = EFFECTIVE_RPS, capacity = EFFECTIVE_RPS)
  - Global semaphore for max concurrency
  - Adaptive RPS control based on recent 429 ratio (window)
  - Respects `Retry-After` (seconds or HTTP-date) with configurable cap
  - Informative logs for throttling and adaptation
- **Concurrency:**
  - Multi-threaded scanning per chain
  - Controlled parallelism for Gecko prefetch
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
See `.env.example` for all variables. Key ones:
- **Telegram:** `TG_BOT_TOKEN`, `TG_CHAT_ID`, `TG_PARSE_MODE`
- **APIs:** `DEXSCREENER_BASE`, `GECKO_BASE`, `CG_ONCHAIN_BASE`, `CG_API_KEY`, `ONCHAIN_PROVIDER`
- **Filters:** `MARKET_CAP_MIN`, `MARKET_CAP_MAX`, `TX24H_MAX`
- **Concurrency:** `CHAIN_SCAN_WORKERS`, `ALERT_FETCH_WORKERS`
- **Dexscreener throttle:** `DS_CALLS_PER_SEC`, `DS_MAX_CONCURRENCY`, `DS_ADAPTIVE_WINDOW`, backoff/recover thresholds and steps

Example `.env` snippet:

```bash
# Discovery/filters
MARKET_CAP_MIN=50000
MARKET_CAP_MAX=800000
TX24H_MAX=2000
CHAINS=base,solana,ethereum

# Loop/concurrency
COOLDOWN_MIN=30
LOOP_SECONDS=60
CHAIN_SCAN_WORKERS=4
ALERT_FETCH_WORKERS=8
MAX_CYCLES=0

# Logging
SAVE_CANDIDATES=true
CANDIDATES_PATH=./candidates.jsonl

# Discovery breadth
SCAN_BY_DEX=true
FALLBACK_BUCKETED_SEARCH=true
BUCKET_ALPHABET=abcdefghijklmnopqrstuvwxyz0123456789
USE_TWO_CHAR_BUCKETS=true
MAX_BUCKETS_PER_CHAIN=1200
BUCKET_DELAY_SEC=0.01
MAX_PAIRS_PER_DEX=5000
BUCKET_SEARCH_TARGET=0
BUCKET_SEARCH_WORKERS=32
BUCKET_RETRY_LIMIT=2

# CoinGecko On-Chain (public REST)
CG_ONCHAIN_BASE=https://api.coingecko.com/api/v3
CG_API_KEY=
CG_TIMEOUT_SEC=20
CG_TTL_SEC=60
ONCHAIN_PROVIDER=coingecko

# Dexscreener throttling/adaptivity (keep as in project)
DS_CALLS_PER_SEC=12
DS_CALLS_PER_SEC_MIN=1
DS_MAX_CONCURRENCY=8
DS_ADAPTIVE_WINDOW=100
DS_BACKOFF_THRESHOLD=0.30
DS_RECOVER_THRESHOLD=0.10
DS_DECREASE_STEP=0.25
DS_INCREASE_STEP=0.10
DS_RETRY_AFTER_CAP_S=3
```

### Tests
Run unit tests:
```bash
pytest -q
```

Covers:
- Address normalization and TOKEN/native determination
- FDV/tx filters
- Alert rule (incl. prev48 == 0 edge case)
- Throttler behavior and adaptive changes
- Gecko TTL cache (no HTTP until TTL expiry)

### Notes
- Works on Windows, macOS, Linux; no POSIX-only dependencies
- No Docker/Poetry required (optional to add later)
