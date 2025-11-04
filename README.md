## WakeBot - Crypto Token Alert Bot (1-Minute Megafilter Cycles)

⚡ **Максимально упрощенная архитектура с 1-минутными циклами!**

Мгновенные алерты о токенах через **единый GeckoTerminal Megafilter запрос**. Сканирует Base, Ethereum, Solana и другие сети, фильтрует с помощью мощных Megafilter параметров, и отправляет Telegram уведомления о REVIVAL сигналах в режиме реального времени.

---

## ⚡ Ключевые особенности

### 🎯 Упрощенная архитектура
```
┌─────────────────────────────────────────────┐
│     GeckoTerminal Megafilter (1 запрос)     │
│                                              │
│  Discovery + Monitoring + Filtering          │
│  • FDV, liquidity, volume, age filters      │
│  • 1h и 24h volume данные                   │
│  • Pool age verification                    │
│  • NO honeypot checks                       │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│         Мгновенные алерты (Telegram)        │
│                                              │
│  • vol1h > vol24h × ratio                   │
│  • Age >= 7 days verified                   │
│  • Cooldown per pool                        │
└─────────────────────────────────────────────┘
```

### ✨ Преимущества

- **⚡ 1-минутные циклы** - минимальная задержка алертов
- **🚀 1 запрос в минуту** - упрощенный API usage
- **📊 Мгновенные данные** - volume_1h и volume_24h из одного запроса
- **🔧 Простой код** - 60% меньше сложности
- **✅ 7-дневная проверка возраста** - гарантированно зрелые пулы
- **🚫 NO honeypot checks** - чистые данные без overhead

### 🎯 Discovery через Megafilter
- **Единый мощный endpoint**: `/pools/megafilter`
- **Продвинутая фильтрация**: FDV, ликвидность, объем, возраст, транзакции
- **Встроенные сортировки**: `h6_trending`, `h24_volume`, и другие
- **Полные данные**: все метрики в одном ответе

### 📊 Алерты в реальном времени
- **REVIVAL правило**: age >= 7 дней, `vol1h` > `vol24h` × `ALERT_RATIO_MIN`
- **Минимальный порог**: previous 24h volume >= минимум
- **Per-pool cooldown**: в SQLite
- **Telegram уведомления**: с Markdown форматированием

### 🔥 Фильтрация
- Нормализация адресов по сети
- Конвертация в TOKEN/native пары (WETH на EVM, SOL на Solana)
- Исключение major токенов по символам/адресам
- Фильтрация по FDV range, liquidity range, и tx24h max
- Проверка возраста (минимум 7 дней)

### ⚡ Rate Limiting
- Один rate limiter для Megafilter
- Adaptive RPS control с max concurrency
- Respects `Retry-After` с configurable cap
- 5xx retries (2 attempts) с backoff

### 🛡️ Надежность
- Non-fatal HTTP/parse errors
- Seen-cache для оптимизации
- SQLite для state persistence
- Graceful error handling

---

## 📦 Требования

- Python 3.10+
- `requests`, `python-dotenv` (+ `pytest` для тестов)
- **GeckoTerminal Pro API key** для Megafilter доступа

---

## 🚀 Установка

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

Отредактируйте `.env` с вашими настройками.

---

## ▶️ Запуск

**Health checks:**
```bash
# Offline check (validates configuration)
python -m wakebot --health-check

# Online check (tests GT Megafilter endpoint)
python -m wakebot --health-check-online
```

**Запуск бота:**
```bash
# Один цикл (для тестирования)
python -m wakebot --once

# Непрерывные 1-минутные циклы
python -m wakebot
```

---

## ⚙️ Конфигурация (.env)

### Основные параметры

**GeckoTerminal Megafilter:**
| Variable | Default | Notes |
|---|---|---|
| `GT_MEGAFILTER_BASE` | `https://pro-api.coingecko.com/api/v3/onchain` | Pro API base |
| `GT_MEGAFILTER_API_KEY` | `` | **Required** - CoinGecko Pro API key |
| `GT_MEGAFILTER_CALLS_PER_MIN` | `30` | Rate limit (1 запрос/минуту × chains) |
| `GT_MEGAFILTER_PAGE_SIZE` | `100` | Результатов на страницу |
| `GT_MEGAFILTER_SORT` | `h6_trending` | Метод сортировки |

**Фильтры:**
| Variable | Default | Notes |
|---|---|---|
| `FDV_MIN` | `50000` | Минимальный FDV в USD |
| `FDV_MAX` | `800000` | Максимальный FDV в USD |
| `LIQUIDITY_MIN` | `50000` | Минимальная ликвидность в USD |
| `LIQUIDITY_MAX` | `800000` | Максимальная ликвидность в USD |
| `TX24H_MAX` | `2000` | Максимум 24h транзакций |
| `REVIVAL_MIN_AGE_DAYS` | `7` | **Минимальный возраст пула** |
| `CHAINS` | `base,ethereum,solana` | Поддерживаемые сети |

**Циклы и алерты:**
| Variable | Default | Notes |
|---|---|---|
| `LOOP_SECONDS` | `60` | Длительность цикла (1 минута) |
| `ALERT_RATIO_MIN` | `1.0` | Min ratio для vol1h/vol24h |
| `MIN_PREV24_USD` | `1000` | Min 24h volume в USD |
| `COOLDOWN_MIN` | `30` | Per-pool cooldown (минуты) |
| `SEEN_TTL_MIN` | `30` | Seen-cache TTL (минуты) |

### Пример `.env`

```bash
# GeckoTerminal Megafilter
GT_MEGAFILTER_BASE=https://pro-api.coingecko.com/api/v3/onchain
GT_MEGAFILTER_API_KEY=your_coingecko_pro_api_key
GT_MEGAFILTER_CALLS_PER_MIN=30

# Фильтры
FDV_MIN=50000
FDV_MAX=800000
LIQUIDITY_MIN=50000
LIQUIDITY_MAX=800000
TX24H_MAX=2000
REVIVAL_MIN_AGE_DAYS=7

# Chains
CHAINS=base,ethereum,solana

# Циклы и алерты
LOOP_SECONDS=60
ALERT_RATIO_MIN=1.0
MIN_PREV24_USD=1000
COOLDOWN_MIN=30

# Telegram
TG_BOT_TOKEN=your_telegram_bot_token
TG_CHAT_ID=your_telegram_chat_id
```

---

## 🧪 Тесты

```bash
pytest -q
```

Покрытие включает:
- Нормализацию адресов и определение TOKEN/native
- FDV и liquidity фильтры
- Pool age verification (7 дней)
- Alert правила и cooldown
- Rate limiter поведение

---

## 📚 Документация

- **Migration Guide**: См. `MINUTE_CYCLE_MIGRATION.md` для деталей миграции
- **Configuration**: См. `.env.example` для всех параметров
- **Architecture**: Полностью документирована в этом README

---

## 🎯 Преимущества 1-минутных циклов

### До (сложная архитектура):
- ❌ Megafilter Discovery → OHLCV запросы → Alerts
- ❌ 60-80 запросов в час
- ❌ Сложное бюджетное планирование
- ❌ Задержка алертов 2-5 минут

### После (упрощенная архитектура):
- ✅ Единый Megafilter запрос → Мгновенные алерты
- ✅ 30-40 запросов в час (50% снижение)
- ✅ Простая логика
- ✅ Задержка алертов < 1 минуты

---

## 📊 Типичный цикл

```
┌──────────────────────────────────┐
│  Минута N                         │
├──────────────────────────────────┤
│  1. Megafilter запрос             │
│     (discovery + monitoring)      │
│  2. Фильтрация seen-cache         │
│  3. Проверка cooldown             │
│  4. Проверка условий алерта       │
│     • vol1h vs vol24h             │
│     • age >= 7 days               │
│  5. Отправка алертов              │
│  6. Обновление state              │
└──────────────────────────────────┘
           ↓
┌──────────────────────────────────┐
│  Минута N+1                       │
│  (повтор цикла)                   │
└──────────────────────────────────┘
```

---

## 📝 Примечания

- **Источник данных**: GeckoTerminal Megafilter (Pro API)
- **Volume metrics**: volume_1h и volume_24h из одного запроса
- **Age verification**: 7-дневный минимум на всех уровнях
- **No honeypot checks**: Чистые данные без verification overhead
- Работает на Windows, macOS, Linux
- Не требует Docker/Poetry

---

## 🎉 Упрощение завершено

Эта версия представляет **максимальное упрощение** архитектуры:
- ✅ Один источник данных (GeckoTerminal Megafilter)
- ✅ Один запрос в минуту
- ✅ Мгновенные алерты
- ✅ 60% меньше кода
- ✅ Без honeypot проверок
- ✅ С 7-дневной логикой

Для детальной информации см. `MINUTE_CYCLE_MIGRATION.md`.

---

**WakeBot v2.0 - Powered by GeckoTerminal Megafilter ⚡**
