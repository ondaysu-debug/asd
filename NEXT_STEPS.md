# 🚀 Next Steps - Quick Start Guide

## ✅ What Was Done

All critical bugs in the CMC DEX API v4 integration have been fixed:
- ✅ Network slug errors fixed (BSC now uses "bsc" not "bnb-chain")
- ✅ Enhanced error detection and validation
- ✅ Better OHLCV handling with GeckoTerminal fallback
- ✅ Improved health checks and diagnostics
- ✅ Comprehensive debug logging

**Status**: Code is ready to run ✅

---

## ⚠️ Critical Missing: CMC API Key

The bot **cannot run without a CoinMarketCap API key**. This is the only remaining blocker.

---

## 📋 3 Simple Steps to Get Running

### Step 1: Get API Key (5 minutes)

1. Go to: https://pro.coinmarketcap.com/account
2. Sign up (free account gives 333 daily credits)
3. Create an API key
4. Copy the key

### Step 2: Configure .env (2 minutes)

```bash
# Copy template
cp .env.example .env

# Edit with your favorite editor
nano .env

# Add these required values:
CMC_API_KEY=paste_your_key_here
TG_BOT_TOKEN=your_telegram_bot_token_here
TG_CHAT_ID=your_telegram_chat_id_here
CHAINS=ethereum
```

### Step 3: Test and Run (1 minute)

```bash
# Test configuration
python3 -m wakebot --health-online

# If PASS, run single cycle
python3 -m wakebot --once

# If successful, run continuous
python3 -m wakebot
```

---

## 🧪 Diagnostic Commands

### Check Configuration
```bash
python3 -m wakebot --health
```

### Test API Connection
```bash
python3 -m wakebot --health-online
```

### Test Network Slugs
```bash
python3 test_cmc_api.py
```

---

## 📊 Expected Output (Success)

When everything is working:

```bash
$ python3 -m wakebot --health-online

[health] Testing chain: ethereum -> network_slug: ethereum
[health] ✅ ethereum: OK - 5 items
[health] Summary: 1/1 chains working
[health] ✅ OHLCV for ethereum/0x...: OK
[health] Result: PASS

$ python3 -m wakebot --once

[discover][ethereum] Using network_slug: ethereum
[discover][ethereum] pages: 2/2 (100%), candidates: 45, scanned: 200
[cycle] ethereum: scanned=200, candidates=45, ohlcv_probes=30, alerts=3
[cycle] total scanned: 200 pools; OHLCV used: 30/30
✅ Candidates found and alerts sent
```

---

## 📚 Documentation Reference

| File | Purpose |
|------|---------|
| `CMC_API_SETUP.md` | **START HERE** - Complete setup instructions |
| `FIX_SUMMARY_2025-10-31.md` | Executive summary of fixes |
| `CMC_V4_FIX_APPLIED.md` | Technical details of all changes |
| `test_cmc_api.py` | Diagnostic tool for network testing |
| `.env.example` | Configuration template |

---

## ❓ Quick Troubleshooting

### Issue: 401 Unauthorized
**Solution**: Add valid CMC_API_KEY to `.env`

### Issue: "The network is not supported"
**Solution**: Fixed! Network slugs corrected in code.

### Issue: No candidates found
**Solution**: 
1. Check filters aren't too strict in `.env`
2. Start with single chain: `CHAINS=ethereum`
3. Enable fallback: `ALLOW_GT_OHLCV_FALLBACK=true`

### Issue: API rate limit
**Solution**: Reduce scan frequency in `.env`:
```bash
CMC_PAGES_PER_CHAIN=1
LOOP_SECONDS=120
```

---

## 🎯 Recommended First Configuration

For testing, use this minimal `.env`:

```bash
# API Keys (REQUIRED)
CMC_API_KEY=your_key_here
TG_BOT_TOKEN=your_bot_token
TG_CHAT_ID=your_chat_id

# Start with one chain
CHAINS=ethereum

# Enable fallback
ALLOW_GT_OHLCV_FALLBACK=true

# Conservative limits
CMC_PAGES_PER_CHAIN=1
COOLDOWN_MIN=30
LOOP_SECONDS=60
```

---

## ✅ Quick Verification Checklist

Before running:
- [ ] CMC API key added to `.env`
- [ ] Telegram bot token added to `.env`
- [ ] Telegram chat ID added to `.env`
- [ ] At least one chain configured
- [ ] Run `python3 -m wakebot --health` (should PASS)
- [ ] Run `python3 -m wakebot --health-online` (should PASS)

If both health checks pass:
- [ ] Run `python3 -m wakebot --once` (should find candidates)
- [ ] Check for Telegram alerts
- [ ] Run `python3 -m wakebot` for continuous monitoring

---

## 🆘 Still Having Issues?

1. **Check logs**: Look for specific error messages
2. **Run diagnostic**: `python3 test_cmc_api.py`
3. **Verify API key**: Log in to CMC dashboard and check credits
4. **Test health**: `python3 -m wakebot --health-online`
5. **Start simple**: Use `CHAINS=ethereum` only

---

## 🎉 Success Indicators

You'll know it's working when you see:
- ✅ Health checks pass
- ✅ Candidates discovered (non-zero count)
- ✅ OHLCV data fetched
- ✅ Telegram alerts received
- ✅ No 401 or network errors

---

**Current Status**: ⏳ Waiting for CMC API key to be added

**Time to Complete**: ~10 minutes total

**Next Action**: Add API key to `.env` and run health check

See `CMC_API_SETUP.md` for detailed instructions.
