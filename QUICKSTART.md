# 🚀 QuickNode Bot - Quick Start Guide

## 📋 Шаги для запуска (5 минут)

### 1️⃣ Получите QuickNode Endpoint

1. Перейдите на [quicknode.com](https://www.quicknode.com/)
2. Создайте аккаунт (есть бесплатный план)
3. Создайте endpoint для **Solana Mainnet**
4. Скопируйте **HTTP Provider URL**

Пример: `https://xxx-yyy-zzz.solana-mainnet.quiknode.pro/abc123/`

---

### 2️⃣ Настройте конфигурацию

```bash
# Скопируйте шаблон
cp .env.example .env

# Откройте в редакторе
nano .env
```

**Заполните минимум:**

```bash
# QuickNode (ОБЯЗАТЕЛЬНО)
QUICKNODE_RPC_URL=https://your-endpoint.solana-mainnet.quiknode.pro/token/

# Telegram (ОБЯЗАТЕЛЬНО для алертов)
TG_BOT_TOKEN=123456:ABC-DEF...
TG_CHAT_ID=-1001234567890

# Сети для мониторинга
CHAINS=solana
```

**Опционально (рекомендуется):**

```bash
# Настройки производительности
QUICKNODE_BATCH_SIZE=100
MAX_MONITORED_POOLS=5000
POOL_REFRESH_INTERVAL_HOURS=6

# Фильтры
FDV_MIN=50000
FDV_MAX=800000
LIQUIDITY_MIN=50000
LIQUIDITY_MAX=800000
REVIVAL_MIN_AGE_DAYS=7
```

---

### 3️⃣ Установите зависимости

```bash
pip install -r requirements.txt
```

**Что устанавливается:**
- `requests` - HTTP клиент
- `python-dotenv` - Загрузка .env
- `base58` - Solana адреса (НОВОЕ!)

---

### 4️⃣ Протестируйте интеграцию

```bash
python test_quicknode_integration.py
```

**Ожидаемый вывод:**

```
🚀 QuickNode Integration Test Suite
================================================================================
TEST 1: QuickNode Configuration
================================================================================
✅ Config loaded successfully
   QuickNode RPC URL: https://xxx.solana-mainnet.quiknode.pro...
   ...

================================================================================
TEST SUMMARY
================================================================================
✅ PASS - config
✅ PASS - solana
✅ PASS - evm
✅ PASS - filtering
✅ PASS - metadata
✅ PASS - volume
================================================================================
TOTAL: 6/6 tests passed
🎉 All tests passed!
```

**Если тесты не прошли:**
- Проверьте `QUICKNODE_RPC_URL` в `.env`
- Убедитесь что endpoint активен
- Проверьте баланс QuickNode (не израсходован ли лимит)

---

### 5️⃣ Запустите бота

#### Вариант A: Одиночный тест-цикл

```bash
python -c "from wakebot.main import run_quicknode_cycle, Config; cfg = Config.load(); run_quicknode_cycle(cfg, cycle_idx=1)"
```

#### Вариант B: Постоянная работа (рекомендуется)

Создайте файл `run_bot.py`:

```python
#!/usr/bin/env python3
from wakebot.main import run_quicknode_cycle, Config
import time

def main():
    cfg = Config.load()
    cycle_idx = 0
    
    print("🚀 QuickNode Bot Starting...")
    print(f"📊 Monitoring chains: {', '.join(cfg.chains)}")
    print(f"⏰ Cycle interval: {cfg.loop_seconds}s")
    print("=" * 80)
    
    while True:
        cycle_idx += 1
        cycle_start = time.monotonic()
        
        try:
            result = run_quicknode_cycle(cfg, cycle_idx=cycle_idx)
            print(f"✅ Cycle {cycle_idx} completed: {result}")
        except Exception as e:
            print(f"❌ Cycle {cycle_idx} error: {e}")
            import traceback
            traceback.print_exc()
        
        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, cfg.loop_seconds - elapsed)
        
        if sleep_for > 0:
            print(f"⏳ Sleeping {sleep_for:.1f}s...\n")
            time.sleep(sleep_for)
        else:
            print(f"⚠️ Cycle overran by {-sleep_for:.1f}s\n")

if __name__ == "__main__":
    main()
```

Запустите:

```bash
python run_bot.py
```

---

## 📊 Что происходит в каждом цикле?

### Цикл 1 (Первый запуск или после 6 часов)

```
1. Сбор пулов     → getProgramAccounts (Raydium)
2. Фильтрация     → TOKEN/NATIVE pairs, возраст > 7 дней
3. Обогащение     → Метаданные, цены, FDV
4. Кеширование    → Сохранение в JSON
5. Мониторинг     → Проверка объемов
6. Алертинг       → Telegram уведомления
```

**Время выполнения:** ~2-5 минут (зависит от QuickNode)

### Циклы 2-N (Каждую минуту)

```
1. Загрузка кеша  → Из JSON файла
2. Мониторинг     → Обновление объемов
3. Алертинг       → Telegram уведомления
```

**Время выполнения:** ~10-30 секунд

---

## 📈 Ожидаемые результаты

### Первый цикл (Full Refresh)

```
🚀 QuickNode cycle bot started. Chains: solana
📊 Using QuickNode for discovery + monitoring
⏰ Min pool age: 7 days
🔄 Pool refresh interval: 6 hours
📈 Max monitored pools: 5000

[discovery][solana] Starting QuickNode discovery...
[solana_collector] Fetching all Raydium pools via QuickNode...
[solana_collector] Successfully decoded 12543 Raydium pools
[pool_filter] Applying filters to 12543 pools...
[pool_filter] After initial filtering: 1834 pools
[pool_filter] Enriching 1834 pools with metadata...
[pool_filter] Final filtered pools: 487

✅ [cycle 1] Total pools for monitoring: 487
📊 [cycle 1] Monitoring 487 pools...
⚡ [cycle 1] Alerts sent: 0
⚡ [cycle 1] Requests: 156, 429s: 0
[rl:quicknode] rps=8.5 tokens=45 p429%=0.0 conc=2
```

### Последующие циклы

```
📊 [cycle 2] Monitoring cached pools...
📊 [cycle 2] Monitoring 487 pools...
⚡ [cycle 2] Alerts sent: 2
⚡ [cycle 2] Requests: 48, 429s: 0
```

---

## 🎯 Telegram алерт - пример

Когда обнаружен всплеск объема, вы получите:

```
🔥 REVIVAL DETECTED! 🔥

🌐 Chain: Solana
💰 Token: BONK ($BONK)
🏊 Pool: 8TQztPGu...

📊 Volume Spike:
   • Last hour: $125,430
   • Last 24h: $2,345,678
   • Ratio: 1.3x

💧 Liquidity: $673,210
📈 FDV: $421,539
⏰ Pool Age: 14 days

🔗 https://dexscreener.com/solana/8TQztPGu...

Source: QuickNode
```

---

## 🔧 Настройка под ваши нужды

### Больше пулов для мониторинга

```bash
MAX_MONITORED_POOLS=10000  # Было 5000
```

### Более частое обновление пулов

```bash
POOL_REFRESH_INTERVAL_HOURS=3  # Было 6
```

### Более строгие фильтры (меньше шума)

```bash
FDV_MIN=100000           # Было 50000
LIQUIDITY_MIN=100000     # Было 50000
REVIVAL_MIN_AGE_DAYS=14  # Было 7
ALERT_RATIO_MIN=1.5      # Было 1.0
```

### Добавить больше сетей

```bash
CHAINS=solana,base,ethereum,bsc
```

**Примечание:** Для EVM нужны отдельные QuickNode endpoints или multi-chain план.

---

## 🆘 Решение проблем

### ❌ "QUICKNODE_RPC_URL not configured"

**Решение:** Добавьте в `.env`:
```bash
QUICKNODE_RPC_URL=https://your-endpoint.solana-mainnet.quiknode.pro/token/
```

### ❌ "429 Too Many Requests"

**Решение:** Уменьшите нагрузку:
```bash
QUICKNODE_BATCH_SIZE=50      # Было 100
LOOP_SECONDS=120             # Было 60
MAX_MONITORED_POOLS=2000     # Было 5000
```

### ❌ "No pools passed filters"

**Решение:** Ослабьте фильтры:
```bash
FDV_MIN=10000
FDV_MAX=10000000
REVIVAL_MIN_AGE_DAYS=1
```

### ❌ "base58.b58encode error"

**Решение:** Установите зависимость:
```bash
pip install base58
```

---

## 📚 Дополнительные ресурсы

- **Полное руководство:** `QUICKNODE_MIGRATION_GUIDE.md`
- **Техническая документация:** `QUICKNODE_MIGRATION_SUMMARY.md`
- **Тестовый скрипт:** `test_quicknode_integration.py`
- **Пример конфигурации:** `.env.example`

---

## ✅ Checklist быстрого старта

- [ ] ✅ Получен QuickNode endpoint
- [ ] ✅ Создан `.env` файл с `QUICKNODE_RPC_URL`
- [ ] ✅ Настроен Telegram бот (`TG_BOT_TOKEN`, `TG_CHAT_ID`)
- [ ] ✅ Установлены зависимости (`pip install -r requirements.txt`)
- [ ] ✅ Пройден тест (`python test_quicknode_integration.py`)
- [ ] ✅ Запущен бот (`python run_bot.py`)
- [ ] ✅ Получен первый алерт в Telegram!

---

**🎉 Готово! Ваш бот работает на QuickNode!**

*Время настройки: ~5 минут*
*Время первого алерта: ~10 минут*

---

**Нужна помощь?**
- QuickNode Support: https://www.quicknode.com/support
- QuickNode Docs: https://www.quicknode.com/docs/solana
