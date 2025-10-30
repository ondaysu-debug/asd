# CMC DEX v4 Discovery Fix Summary

## Problem
All CMC discovery requests were failing with 400 errors because the `category` parameter is no longer supported in the `/v4/dex/spot-pairs/latest` endpoint.

## Changes Made

### 1. config.py
- **Added**: `cmc_chain_slugs` mapping with fallback variants for each chain
  - ethereum: `["ethereum"]`
  - solana: `["solana"]`
  - base: `["base", "basescan", "base-mainnet"]`
  - bsc: `["bnb", "bsc", "binance-smart-chain"]`
- **Purpose**: Support automatic fallback on 400 errors by trying multiple chain slug variants

### 2. net_http.py
- **Added**: Logging of response body (truncated to 600 chars) for all 4xx errors in `cmc_get_json()`
- **Purpose**: Improve debugging by showing API error messages in logs
- **Location**: Lines 192-198, logs as `[cmc] {status} error: {body_snippet}`

### 3. discovery.py
#### Main Changes:
- **Removed**: `category` parameter from all CMC API URLs
- **Changed URL format**: 
  - Before: `/v4/dex/spot-pairs/latest?chain_slug={chain}&category={new|trending|all}&page={page}&limit={limit}`
  - After: `/v4/dex/spot-pairs/latest?chain_slug={chain}&page={page}&limit={limit}`

#### Local Sorting Implementation:
Since the API no longer filters by category, we now fetch all pools and sort locally:
- **"new" source**: Sort by `listed_at` or `pool_created_at` descending (newest first)
- **"trending" source**: Sort by `volume_24h_quote` descending (highest volume first)
- **"all" source**: Keep as returned by API (no additional sorting)

#### Chain Slug Fallback:
- **Added**: `_fetch_page_with_fallback()` function that tries each chain slug variant on 400 errors
- **Behavior**: Iterates through variants until first successful (200) response
- **Logging**: Prints which variant failed and continues to next

#### DEX Discovery:
- **Changed**: `/v4/dex/dexes?chain_slug={chain}` (list dexes) also uses fallback
- **Changed**: `/spot-pairs/latest?chain_slug={chain}&dex_id={dex_id}&page={page}&limit={limit}` (no category)

#### Additional Fields:
- **Added**: Extract `volume_24h` and `listed_at` from API response for sorting
- **Added**: Store these fields in candidate dictionaries for later use

### 4. main.py
- **Updated**: `health_check_online()` to use correct endpoint without `category` parameter
- **Changed**: 
  - Before: `/spot-pairs/latest?chain_slug={cmc_chain}&category=new&page=1&limit=5`
  - After: `/spot-pairs/latest?chain_slug={cmc_chain}&page=1&limit=5`

### 5. tests/test_alerts.py
- **Fixed**: Added missing `dq_discrepancy_threshold=0.25` parameter to test config
- **Purpose**: Ensure tests pass with updated Config dataclass signature

## Testing
- ✅ All 10 tests pass successfully
- ✅ No linter errors
- ✅ All modules import correctly

## Expected Behavior
1. Discovery requests will no longer include invalid `category` parameter
2. API will return all pools without category filtering
3. Local sorting will provide "new" and "trending" views client-side
4. On 400 errors, system will automatically try alternative chain slug variants
5. Detailed error logs will help identify any remaining API issues
6. Discovery should now successfully return candidates instead of failing with 400

## Endpoints Used
- **Discovery**: `GET /v4/dex/spot-pairs/latest?chain_slug={chain}&page={page}&limit={limit}`
- **DEX List**: `GET /v4/dex/dexes?chain_slug={chain}`
- **DEX Pairs**: `GET /v4/dex/spot-pairs/latest?chain_slug={chain}&dex_id={dex_id}&page={page}&limit={limit}`
- **OHLCV**: `GET /v4/dex/pairs/ohlcv/latest?chain_slug={chain}&pair_address={pair}&timeframe=1h&aggregate=1&limit=2`

All endpoints now work without the deprecated `category` parameter.
