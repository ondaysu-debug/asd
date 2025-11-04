## WakeBot - Crypto Token Alert Bot (GeckoTerminal Megafilter Edition)

🚀 **Fully migrated to GeckoTerminal Megafilter architecture!**

Reliable TOKEN/native discovery and alerts using **GeckoTerminal Megafilter** for discovery and **GeckoTerminal OHLCV** for monitoring. Scans Base, Ethereum, Solana, and more, filters noise with powerful Megafilter parameters, fetches precise OHLCV windows, and sends Telegram notifications for REVIVAL signals.

### ✨ Key Features

- **Discovery (GT Megafilter):**
  - Single powerful endpoint: `/pools/megafilter`
  - Advanced filtering: FDV, liquidity, volume, age, transactions
  - Trending sorts: `h6_trending`, `h24_volume`, etc.
  - **7-day minimum pool age** enforcement
  - **NO honeypot checks** (clean data)
  
- **Filtering:**
  - Normalize addresses by chain
  - Convert to TOKEN/native pairs (WETH on EVM, SOL on Solana)
  - Exclude majors/mimics by symbol/addresses
  - Filter by FDV range, liquidity range, and tx24h max
  - Age-based filtering (minimum 7 days)
  
- **Metrics (GT OHLCV 25h):**
  - Fetch 25 hourly candles per pool (`limit=25`)
  - Derive `vol1h` (last hour) and `prev24h` (24 hours before last)
  - TTL cache for OHLCV results (configurable)
  - Age verification through pool creation timestamp
  
- **Alerts:**
  - REVIVAL rule: age >= 7 days, `vol1h` > `prev24h` × `ALERT_RATIO_MIN`
  - Minimum previous 24h volume threshold
  - Per-pool cooldown in SQLite
  - Telegram notifications with Markdown escaping
  
- **Rate limiting:**
  - Separate rate limiters for Megafilter (Pro API) and OHLCV (Public API)
  - Adaptive RPS control with max concurrency
  - Dynamic per-cycle HTTP budget with 429 penalty awareness
  - Respects `Retry-After` (seconds or HTTP-date) with configurable cap
  - 5xx retries (2 attempts) with small backoff
  
- **Concurrency:**
  - Multi-threaded chain scanning and alert fetch
  
- **Logging:**
  - Candidates logged to JSONL with timestamps
  
- **Resilience:**
  - Non-fatal HTTP/parse errors; skips and continues

### 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    GeckoTerminal Megafilter                  │
│            (pro-api.coingecko.com/api/v3/onchain)           │
│                                                              │
│  Discovery with powerful filters:                           │
│  • FDV range (min/max)                                      │
│  • Liquidity range (min/max)                                │
│  • 24h volume minimum                                       │
│  • Pool age minimum (7 days = 168 hours)                   │
│  • Transaction count maximum                                 │
│  • NO honeypot checks                                       │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│              Additional Filters (wakebot/filters.py)         │
│  • Native pair validation                                    │
│  • Base token acceptance                                     │
│  • Age verification (7 days)                                 │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                  GeckoTerminal OHLCV                         │
│           (api.geckoterminal.com/api/v2)                    │
│                                                              │
│  Monitoring with 25h candles:                               │
│  • vol1h (last hour volume)                                 │
│  • prev24h (previous 24 hours)                              │
│  • Age verification                                          │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                        Alerts                                │
│  • REVIVAL: vol1h > prev24h × ratio                         │
│  • Age >= 7 days verified                                   │
│  • Cooldown per pool                                         │
│  • Telegram notifications                                    │
└─────────────────────────────────────────────────────────────┘
```

### 📦 Requirements

- Python 3.10+
- Only standard library + `requests`, `python-dotenv` (and `pytest` for tests)
- **GeckoTerminal Pro API key** for Megafilter access

### 🚀 Installation

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your configuration (see below).

### ▶️ Running

**Health checks:**
```bash
# Offline check (validates configuration)
python -m wakebot --health-check

# Online check (tests GT Megafilter and OHLCV endpoints)
python -m wakebot --health-check-online
```

**Run the bot:**
```bash
# Continuous loop
python -m wakebot

# Or use main module directly
python -m wakebot.main
```

### ⚙️ Configuration (.env)

See `.env.example` for all variables. Key ones and defaults:

**GeckoTerminal Megafilter (Discovery):**
| Variable | Default | Notes |
|---|---|---|
| `GT_MEGAFILTER_BASE` | `https://pro-api.coingecko.com/api/v3/onchain` | Pro API base |
| `GT_MEGAFILTER_API_KEY` | `` | **Required** - Your CoinGecko Pro API key |
| `GT_MEGAFILTER_CALLS_PER_MIN` | `60` | Rate limit for Megafilter |
| `GT_MEGAFILTER_PAGE_SIZE` | `100` | Results per page |
| `GT_MEGAFILTER_PAGES_PER_CYCLE` | `3` | Pages per cycle |
| `GT_MEGAFILTER_SORT` | `h6_trending` | Sort method |

**GeckoTerminal OHLCV (Monitoring):**
| Variable | Default | Notes |
|---|---|---|
| `GECKO_BASE` | `https://api.geckoterminal.com/api/v2` | Public API base |
| `GECKO_CALLS_PER_MIN` | `60` | Rate limit for OHLCV |
| `GECKO_RETRY_AFTER_CAP_S` | `15.0` | Cap for Retry-After |
| `GECKO_TTL_SEC` | `60` | OHLCV cache TTL |

**Filters:**
| Variable | Default | Notes |
|---|---|---|
| `FDV_MIN` | `50000` | Minimum FDV in USD |
| `FDV_MAX` | `800000` | Maximum FDV in USD |
| `LIQUIDITY_MIN` | `50000` | Minimum liquidity in USD |
| `LIQUIDITY_MAX` | `800000` | Maximum liquidity in USD |
| `TX24H_MAX` | `2000` | Maximum 24h transactions |
| `REVIVAL_MIN_AGE_DAYS` | `7` | **Minimum pool age (7 days)** |
| `CHAINS` | `base,ethereum,solana` | Supported chains |

**Budget and Rate Limiting:**
| Variable | Default | Notes |
|---|---|---|
| `MAX_OHLCV_PROBES_CAP` | `100` | Max OHLCV probes per cycle |
| `GECKO_SAFETY_BUDGET` | `10` | Reserve HTTP calls |
| `MIN_OHLCV_PROBES` | `5` | Minimum probes if budget allows |

**Alerting:**
| Variable | Default | Notes |
|---|---|---|
| `ALERT_RATIO_MIN` | `1.0` | Min ratio for vol1h/prev24h |
| `MIN_PREV24_USD` | `1000` | Min 24h volume in USD |
| `COOLDOWN_MIN` | `30` | Per-pool alert cooldown (minutes) |
| `SEEN_TTL_MIN` | `30` | Skip OHLCV for seen pools (minutes) |

**Loop and Concurrency:**
| Variable | Default | Notes |
|---|---|---|
| `LOOP_SECONDS` | `60` | Target loop duration |
| `CHAIN_SCAN_WORKERS` | `4` | Parallel chain discovery |
| `ALERT_FETCH_WORKERS` | `8` | Parallel alert checks |
| `MAX_CYCLES` | `0` | Max cycles (0 = infinite) |

**Example `.env` snippet:**

```bash
# GeckoTerminal Megafilter (Discovery)
GT_MEGAFILTER_BASE=https://pro-api.coingecko.com/api/v3/onchain
GT_MEGAFILTER_API_KEY=your_coingecko_pro_api_key
GT_MEGAFILTER_CALLS_PER_MIN=60

# GeckoTerminal OHLCV (Monitoring)
GECKO_BASE=https://api.geckoterminal.com/api/v2
GECKO_CALLS_PER_MIN=60

# Filters
FDV_MIN=50000
FDV_MAX=800000
LIQUIDITY_MIN=50000
LIQUIDITY_MAX=800000
TX24H_MAX=2000
REVIVAL_MIN_AGE_DAYS=7

# Chains
CHAINS=base,ethereum,solana

# Alerting
ALERT_RATIO_MIN=1.0
MIN_PREV24_USD=1000
COOLDOWN_MIN=30

# Telegram
TG_BOT_TOKEN=your_telegram_bot_token
TG_CHAT_ID=your_telegram_chat_id
```

### 🧪 Tests

Run unit tests:
```bash
pytest -q
```

Coverage includes:
- Address normalization and TOKEN/native determination
- FDV and liquidity filters
- Pool age verification (7 days)
- Alert rule and cooldown
- Rate limiter behavior and adaptive changes
- OHLCV cache TTL

### 📚 Documentation

- **Migration Guide**: See `GT_MEGAFILTER_MIGRATION.md` for detailed migration information
- **Configuration**: See `.env.example` for all available parameters
- **Architecture**: Fully documented in this README and migration guide

### 🔑 Key Differences from Previous Version

**Before (Hybrid CMC+GT):**
- ❌ Complex dual API configuration
- ❌ CMC rate limits
- ❌ GT fallback complexity
- ❌ Mixed data sources

**After (Pure GT Megafilter):**
- ✅ Single unified architecture
- ✅ Powerful Megafilter discovery
- ✅ Dedicated OHLCV monitoring
- ✅ Simplified configuration
- ✅ Better filtering capabilities
- ✅ **NO honeypot checks**
- ✅ **7-day age enforcement at all levels**

### 📝 Notes

- **Primary data source**: GeckoTerminal Megafilter (Pro API) for discovery
- **Monitoring**: GeckoTerminal OHLCV (Public API) for volume metrics
- **Age verification**: 7-day minimum enforced at discovery, filtering, and alerting levels
- **No honeypot checks**: Clean data without honeypot verification overhead
- Works on Windows, macOS, Linux; no POSIX-only dependencies
- No Docker/Poetry required (optional to add later)

### 🎉 Migration Complete

This version represents a complete migration from the hybrid CMC+GT architecture to a pure GeckoTerminal implementation. All CMC dependencies have been removed, and the codebase has been significantly simplified while maintaining all core functionality.

For detailed migration information, see `GT_MEGAFILTER_MIGRATION.md`.
