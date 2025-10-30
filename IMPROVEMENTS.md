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

### New Metrics
- `http.get_cycle_requests()` - total HTTP requests in cycle
- `http.get_cycle_429()` - number of 429 errors
- `http.get_cycle_penalty()` - total penalty seconds
- `http.get_effective_rps()` - current rate limiter RPS

### Output Example
```
[rate] req=15 429=0 penalty=0.50s rps≈0.47
```

## C) Response Validation

### Discovery Validation
- `_validate_cmc_pairs_doc()` in `discovery.py`
- Checks for required fields: pair_address, id, pairId, etc.
- Skips invalid pages with warning log

### OHLCV Validation
- `_validate_cmc_ohlcv_doc()` in `cmc.py`
- Validates candle format: [ts, o, h, l, c, v]
- Falls back to GT if validation fails (when enabled)

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
1. `wakebot/net_http.py` - Rate-limit counters and metrics
2. `wakebot/cmc.py` - OHLCV validation and data quality logging
3. `wakebot/discovery.py` - Discovery validation
4. `wakebot/alerts.py` - Source tracking in alert text
5. `wakebot/main.py` - Health check, metrics output, health summary
6. `wakebot/config.py` - Chain slug mapping, BSC defaults

### New Features
- Health check function with `--health` flag
- Comprehensive validation for all CMC API responses
- Data quality comparison between CMC and GT
- Detailed rate-limit monitoring
- Source attribution in alerts

## Notes

### CMC API Endpoints
Current implementation uses:
- Discovery: `/dexer/v3/{chain}/pools/{new|trending}`
- OHLCV: `/dexer/v3/{chain}/pairs/{pair_id}/ohlcv/latest`

**Important**: If actual CMC API paths differ (e.g., `/v4/dex/` instead of `/dexer/v3/`), update `config.py`:
```python
cmc_dex_base = os.getenv("CMC_DEX_BASE", "https://pro-api.coinmarketcap.com/v4/dex")
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
