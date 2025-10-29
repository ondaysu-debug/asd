## WakeBot - Crypto Token Alert Bot

A reliable bot that discovers TOKEN/native pools across Base, Solana, and Ethereum using Dexscreener, fetches metrics from GeckoTerminal, and triggers Telegram alerts when the last 1h volume exceeds the previous 48h volume (excluding the current hour).

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
  - Pull `volume_usd.h1/h48` and `transactions.h1` from GeckoTerminal
  - TTL cache (thread-safe)
  - Fallback on Dexscreener volumes if Gecko returns zeros (no alert if vol48h == 0)
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
- **APIs:** `DEXSCREENER_BASE`, `GECKO_BASE`
- **Filters:** `MARKET_CAP_MIN`, `MARKET_CAP_MAX`, `TX24H_MAX`
- **Concurrency:** `CHAIN_SCAN_WORKERS`, `ALERT_FETCH_WORKERS`
- **Dexscreener throttle:** `DS_CALLS_PER_SEC`, `DS_MAX_CONCURRENCY`, `DS_ADAPTIVE_WINDOW`, backoff/recover thresholds and steps

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
