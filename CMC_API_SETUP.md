# 🔑 CoinMarketCap API Setup Instructions

## Critical Issue Identified

The bot **cannot work without a valid CoinMarketCap API key**. The diagnostic test revealed:

```
API Key: ✗ Missing
Error: 401 Client Error: Unauthorized
```

## How to Fix

### Step 1: Get CoinMarketCap API Key

1. Go to https://pro.coinmarketcap.com/account
2. Sign up or log in
3. Navigate to API Keys section
4. Create a new API key (Basic plan is free and includes 333 daily credits)
5. Copy your API key

### Step 2: Configure .env File

Update your `.env` file with the API key:

```bash
# Copy the example file if needed
cp .env.example .env

# Edit .env and add your credentials
nano .env
```

Add these **required** settings:

```bash
# ============= REQUIRED =============
CMC_API_KEY=your_actual_cmc_api_key_here
TG_BOT_TOKEN=your_telegram_bot_token
TG_CHAT_ID=your_telegram_chat_id

# ============= RECOMMENDED =============
CHAINS=ethereum
ALLOW_GT_OHLCV_FALLBACK=true
CMC_PAGES_PER_CHAIN=1
COOLDOWN_MIN=30
LOOP_SECONDS=60
```

### Step 3: Test the Configuration

```bash
# Run health check
python3 -m wakebot --health

# Run online health check (tests API connection)
python3 -m wakebot --health-online

# Run single cycle
python3 -m wakebot --once
```

## What Was Fixed

### 1. ✅ Network Slug Mapping (config.py)
- **Fixed**: Changed `"bsc": "bnb-chain"` → `"bsc": "bsc"`
- **Added**: Support for additional chains (base, solana, polygon, arbitrum, optimism, avalanche)

### 2. ✅ Enhanced Response Validation (discovery.py)
- Improved `_validate_cmc_pairs_doc()` with comprehensive error checking
- Added detection of API error codes and messages
- Support for alternative data structures
- Detailed debug logging

### 3. ✅ Better Error Handling (cmc.py)
- Added API error detection before processing OHLCV data
- Improved fallback to GeckoTerminal when CMC fails
- Enhanced debug logging for troubleshooting

### 4. ✅ Enhanced Health Checks (main.py)
- `--health`: Tests configuration validity (offline)
- `--health-online`: Tests each chain's network_slug with CMC API (online)
- Per-chain status reporting
- Detailed error messages

### 5. ✅ Diagnostic Test Script (test_cmc_api.py)
- Tests all possible network_slug values
- Identifies working vs failing chains
- Provides configuration recommendations

## Expected Results After Setup

Once you add a valid CMC API key:

```bash
$ python3 -m wakebot --health-online

[health] Testing chain: ethereum -> network_slug: ethereum
[health] ✅ ethereum: OK - 5 items
[health] Testing chain: bsc -> network_slug: bsc
[health] ✅ bsc: OK - 5 items

[health] Summary: 2/2 chains working
[health] Working: ethereum, bsc
[health] ✅ OHLCV for ethereum/0x...: OK
[health] Result: PASS
```

## Troubleshooting

### Issue: Still getting 401 errors
- **Solution**: Double-check your API key is correctly copied to `.env`
- Ensure no extra spaces or quotes around the key
- Verify the key is active in your CMC account

### Issue: "The network is not supported"
- **Solution**: The network_slug fix should resolve this
- Use `python3 test_cmc_api.py` to verify which networks work
- Start with just `CHAINS=ethereum` to test

### Issue: No candidates found
- **Solution**: Check your filters aren't too strict:
  ```bash
  LIQUIDITY_MIN=50000    # Lower if needed
  LIQUIDITY_MAX=800000   # Raise if needed
  TX24H_MAX=2000         # Raise if needed
  ```

### Issue: API rate limits
- **Solution**: Reduce scan frequency:
  ```bash
  CMC_PAGES_PER_CHAIN=1
  LOOP_SECONDS=120
  CHAIN_SCAN_WORKERS=2
  ```

## Next Steps

1. ✅ Add CMC API key to `.env`
2. ✅ Add Telegram bot credentials
3. ✅ Run `python3 -m wakebot --health-online`
4. ✅ If health check passes, run `python3 -m wakebot --once`
5. ✅ Monitor logs for candidates and alerts
6. ✅ If working, run continuous mode: `python3 -m wakebot`

## Support

If you continue to have issues:
1. Run `python3 test_cmc_api.py` and share the output
2. Check `candidates.jsonl` to see if any pools are being discovered
3. Review logs for specific error messages
4. Verify your CMC API plan has available credits

---

**Note**: The free CMC API plan provides 333 daily credits. Each discovery page and OHLCV request consumes 1 credit. The bot is configured to stay well within this limit.
