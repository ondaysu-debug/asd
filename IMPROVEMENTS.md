# WakeBot CMC Migration - Improvements Summary

This document describes the enhancements added to WakeBot as part of the migration to CoinMarketCap DEX API.

## A) Health Check

### Features
- New `--health` CLI flag for quick API availability check
- Tests both discovery and OHLCV endpoints
- Returns exit code 0 (pass) or 1 (fail)

### Usage
```bash
python3 -m wakebot.main --health
```

### Implementation
- `health_check()` function in `main.py`
- Performs minimal API calls (1 discovery page, 1 OHLCV request)
- No side effects (no DB writes, no alerts)

## B) Rate-Limit Monitoring

### Features
- Per-cycle HTTP request tracking
- 429 error counting
- Penalty time accumulation (Retry-After sleep)
- Effective RPS reporting
- **✅ NEW**: Limiter health snapshots with `snapshot()` method
- **✅ NEW**: Per-limiter health logging with `log_ratelimit_health()`

### New Metrics
- `http.get_cycle_requests()` - total HTTP requests in cycle
- `http.get_cycle_429()` - number of 429 errors
- `http.get_cycle_penalty()` - total penalty seconds
- `http.get_effective_rps()` - current rate limiter RPS
- **✅ NEW**: `limiter.snapshot()` - returns dict with `effective_rps`, `tokens`, `p429_pct`, `concurrency`
- **✅ NEW**: `http.log_ratelimit_health(prefix)` - logs limiter state snapshot

### Output Example
```
[rate] req=15 429=0 penalty=0.50s rps≈0.47
[rl:cmc] rps=0.467 tokens=0.85 p429%=2.3 conc=8
[rl:gt] rps=0.450 tokens=1.20 p429%=0.0 conc=6
```

## C) Response Validation

### Discovery Validation
- `_validate_cmc_pairs_doc()` in `discovery.py`
- Checks for required fields: pair_address, id, pairId, etc.
- Skips invalid pages with warning log

### OHLCV Validation
- **✅ ENHANCED**: `_validate_cmc_ohlcv_doc()` in `cmc.py` now uses strict validation
- Raises `ValueError` with detailed error messages on validation failure
- Validates response structure: `{"data": {"attributes": {"candles": [...]}}}`
- Validates each candle: must be list/tuple with ≥6 numeric elements `[ts,o,h,l,c,v]`
- Falls back to GT if validation fails (when `allow_gt_ohlcv_fallback=true`)

### Log Format
```
[cmc][validate] unexpected discovery schema; skipping chain/source page N
[cmc][validate] unexpected ohlcv schema for pair=X; fallback? true
```

## D) Data Quality Logging

### Features
- Compares CMC vs GT OHLCV data when both available
- Calculates absolute and relative discrepancies
- Warns on >25% differences

### Implementation
- `_log_data_quality()` in `cmc.py`
- Automatic comparison in fallback scenarios
- Configurable threshold: `DQ_DISCREPANCY_THRESHOLD = 0.25`

### Output Example
```
[dq] ethereum/0xabc v1h CMC=1234.56 GT=1200.00 Δ=34.56 (2.8%); prev24 CMC=50000.00 GT=51000.00 Δ=1000.00 (2.0%)
[dq][warn] ⚠️  discrepancy >25% for solana/0xdef
```

## E) Final Touches

### Alert Source Tracking
- Alerts now indicate data source: "CMC DEX" or "CMC→GT fallback"
- Added `source` parameter to `build_revival_text_cmc()`

### Health Summary
- End-of-cycle summary with key metrics
- Format: `[health] ok=true discovery_pages=X/Y scanned=Z ohlcv_used=A/B`
- Includes first error if cycle failed

### Default Chains
- BSC included in default chains: `base,solana,ethereum,bsc`
- Chain slug mapping: `bsc -> bnb` (for CMC API)

## Testing

### Commands
```bash
# Syntax check
python3 -m py_compile wakebot/*.py

# Import test
python3 -c "from wakebot import main, cmc, discovery; print('OK')"

# Health check
python3 -m wakebot.main --health

# Single cycle
python3 -m wakebot.main --once

# Full test suite
python3 -m pytest tests/ -v
```

### Test Results
- All 10 tests passing
- No regressions in existing functionality
- New features working as expected

## Configuration

### New Environment Variables
```bash
# Data quality threshold (default: 25%)
export DQ_DISCREPANCY_THRESHOLD=0.25

# Enable GT fallback for OHLCV
export ALLOW_GT_OHLCV_FALLBACK=true

# CMC API configuration (already present)
export CMC_API_KEY="your-key"
export CMC_CALLS_PER_MIN=28
export CMC_RETRY_AFTER_CAP_S=3.0
```

## File Changes

### Modified Files
1. **✅ `wakebot/rate_limit.py`** - Added `snapshot()` method for monitoring
2. **✅ `wakebot/net_http.py`** - Added `log_ratelimit_health()`, rate-limit counters and metrics
3. **✅ `wakebot/cmc.py`** - Enhanced strict OHLCV validation, data quality logging, **v4 endpoint migration**
4. **✅ `wakebot/discovery.py`** - Discovery validation, **v4 endpoint migration**
5. `wakebot/alerts.py` - Source tracking in alert text
6. **✅ `wakebot/main.py`** - Health check with **v4 endpoints**, metrics output, limiter health logging
7. **✅ `wakebot/config.py`** - **v4 API base URLs**, chain slug mapping, BSC defaults

### New Features
- Health check function with `--health` flag
- Comprehensive validation for all CMC API responses
- Data quality comparison between CMC and GT
- Detailed rate-limit monitoring
- Source attribution in alerts

## Notes

### CMC API Endpoints (Updated to v4)
**✅ UPDATED** to actual CMC DEX API v4 (as of 2025):
- Discovery: `/v4/dex/spot-pairs/latest?chain_slug={chain}&category={new|trending|all}&page={page}&limit={limit}`
- OHLCV: `/v4/dex/pairs/ohlcv/latest?chain_slug={chain}&pair_address={pool_id}&timeframe=1h&aggregate=1&limit=25`
- Dexes list: `/v4/dex/dexes?chain_slug={chain}`

Default base URLs in `config.py`:
```python
cmc_dex_base = "https://api.coinmarketcap.com/v4/dex"
cmc_dex_base_alt = "https://pro-api.coinmarketcap.com/v4/dex"
```

### Validation Benefits
- Early detection of API schema changes
- Graceful degradation (fallback to GT)
- Better debugging through detailed logs
- No silent failures

### Rate-Limit Benefits
- Visibility into API usage patterns
- Early warning for approaching limits
- Better capacity planning
- Penalty tracking for budget optimization
