# 🚀 QuickNode Migration Guide

## Обзор

Этот гайд описывает полную миграцию бота для мониторинга DeFi пулов с GeckoTerminal/Raydium API на **QuickNode API**.

## 🎯 Что было сделано

### Новые модули

Создана полная инфраструктура QuickNode в директории `/wakebot/quicknode/`:

1. **`solana_collector.py`** - Сбор всех Raydium пулов через `getProgramAccounts`
2. **`evm_collector.py`** - Сбор пулов для Base, Ethereum, BSC через события
3. **`pool_filter.py`** - Фильтрация пулов по критериям (возраст, ликвидность, FDV)
4. **`volume_monitor.py`** - Мониторинг объемов через транзакции/события
5. **`token_metadata.py`** - Получение метаданных токенов (symbol, decimals, supply)
6. **`price_calculator.py`** - Расчет цен, ликвидности и FDV

### Обновленные модули

1. **`config.py`** - Добавлена конфигурация QuickNode
2. **`net_http.py`** - Добавлены методы для QuickNode RPC/batch запросов
3. **`discovery.py`** - Новая функция `unified_quicknode_discovery()`
4. **`main.py`** - Новая функция `run_quicknode_cycle()` для работы с QuickNode

## 📋 Настройка

### 1. Получение QuickNode Endpoint

1. Зарегистрируйтесь на [quicknode.com](https://www.quicknode.com/)
2. Создайте endpoint для нужной сети:
   - **Solana Mainnet** - для Raydium пулов
   - **Ethereum/Base/BSC** - для EVM пулов
3. Скопируйте HTTP Provider URL

### 2. Конфигурация .env

Создайте `.env` файл на основе `.env.example`:

```bash
# QuickNode Configuration (ОБЯЗАТЕЛЬНО)
QUICKNODE_RPC_URL=https://your-endpoint.solana-mainnet.quiknode.pro/your-token/
QUICKNODE_WS_URL=wss://your-endpoint.solana-mainnet.quiknode.pro/your-token/
QUICKNODE_API_KEY=  # Опционально

# Performance Settings
QUICKNODE_BATCH_SIZE=100
POOL_REFRESH_INTERVAL_HOURS=6
MAX_MONITORED_POOLS=5000

# Telegram (для алертов)
TG_BOT_TOKEN=your_telegram_bot_token
TG_CHAT_ID=your_chat_id

# Chains для мониторинга
CHAINS=solana,base,ethereum

# Фильтры
FDV_MIN=50000
FDV_MAX=800000
LIQUIDITY_MIN=50000
LIQUIDITY_MAX=800000
REVIVAL_MIN_AGE_DAYS=7
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

Новая зависимость: `base58` для работы с Solana адресами.

## 🚀 Запуск

### Тестирование интеграции

Перед запуском бота протестируйте QuickNode интеграцию:

```bash
python test_quicknode_integration.py
```

Этот скрипт проверит:
- ✅ Загрузку конфигурации
- ✅ Сбор Solana пулов
- ✅ Сбор EVM пулов
- ✅ Фильтрацию пулов
- ✅ Получение метаданных токенов
- ✅ Инициализацию мониторинга объемов

### Запуск бота с QuickNode

Обновите `wakebot/__main__.py` для использования QuickNode:

```python
from .main import run_quicknode_cycle

# В главном цикле
while True:
    cycle_idx += 1
    result = run_quicknode_cycle(cfg, cycle_idx=cycle_idx)
    # ...
```

Или запустите напрямую:

```bash
python -m wakebot
```

## 🔄 Архитектура работы

### Цикл 1: Full Refresh (каждые N часов)

```
QuickNode RPC → Collect ALL pools → Filter → Enrich metadata → Cache
                                                                    ↓
                                                            5000 best pools
```

### Цикл 2-N: Monitoring Only

```
Load cached pools → Update volumes → Check alerts → Update cache
                                            ↓
                                    Send Telegram alerts
```

### Ключевые особенности

1. **Массовый сбор**: Получаем ВСЕ пулы Raydium за один `getProgramAccounts` запрос
2. **Кеширование**: Обновляем список пулов только раз в N часов (настраивается)
3. **Мониторинг**: Каждую минуту проверяем объемы только для отфильтрованных пулов
4. **Batch запросы**: Группируем RPC запросы для эффективности

## 📊 Фильтрация пулов

Пулы проходят многоступенчатую фильтрацию:

### Этап 1: Initial Filters (быстрые)
- ✅ TOKEN/NATIVE пара (не NATIVE/NATIVE)
- ✅ Активный статус пула

### Этап 2: Metadata Enrichment
- Получаем creation time
- Рассчитываем ликвидность USD
- Рассчитываем FDV

### Этап 3: Advanced Filters
- ✅ Возраст пула > 7 дней
- ✅ Ликвидность: $50k - $800k
- ✅ FDV: $50k - $800k
- ✅ Транзакции 24h < 2000

## ⚠️ Важные ограничения

### 1. Solana: Парсинг бинарных данных

Raydium AMM пулы используют бинарную структуру. Offsets могут меняться:

```python
# Текущие offsets для Raydium V4
version = decoded_data[0]           # offset 0
status = decoded_data[1]            # offset 1
base_mint = decoded_data[8:40]      # offset 8-40
quote_mint = decoded_data[40:72]    # offset 40-72
base_amount = decoded_data[376:384] # offset 376-384
```

**Решение**: Проверяйте документацию Raydium при обновлениях.

### 2. EVM: Ограничения eth_getLogs

Запросы `eth_getLogs` с большим диапазоном блоков могут быть медленными.

**Текущая реализация**: Последние 10k блоков (~1-2 дня)

**Для production**: 
- Используйте инкрементальный подход
- Или интегрируйте The Graph через QuickNode

### 3. Rate Limiting

QuickNode имеет лимиты на тарифных планах:

- Free: ~10 RPS
- Growth: ~25 RPS
- Pro: ~100+ RPS

**Настройка** в `config.py`:
```python
quicknode_batch_size = 100  # Размер батчей
```

### 4. Расчет объемов

Текущая реализация использует **упрощенные метрики**:

```python
# Solana: количество транзакций как прокси объема
volume_24h = len(transactions_24h)

# EVM: количество Swap событий
volume_24h = len(swap_events)
```

**Для точного расчета**: Нужно парсить данные транзакций/событий для получения реальных amounts.

## 🔧 Оптимизация производительности

### 1. Batch RPC запросы

Вместо:
```python
for pool in pools:
    volume = get_volume(pool)  # N запросов
```

Используйте:
```python
volumes = batch_get_volumes(pools)  # 1 запрос
```

### 2. Кеширование

- Пулы кешируются на N часов (default: 6)
- Метаданные токенов кешируются в памяти
- Объемы обновляются каждый цикл

### 3. Параллелизм

Разные chains обрабатываются параллельно:

```python
max_workers = min(len(chains), cfg.chain_scan_workers)
with ThreadPoolExecutor(max_workers=max_workers) as pool:
    # Параллельный сбор
```

## 📈 Мониторинг и отладка

### Логи

Бот выводит детальные логи:

```
[discovery][solana] Starting QuickNode discovery...
[solana_collector] Fetching all Raydium pools via QuickNode...
[solana_collector] Successfully decoded 12543 Raydium pools
[pool_filter] Applying filters to 12543 pools...
[pool_filter] Filter results: 1234/12543 pools passed initial filters
```

### Метрики

Отслеживайте:
- `requests` - Количество RPC запросов за цикл
- `429s` - Количество rate limit ошибок
- `rps` - Эффективный RPS rate limiter

### Health Check

```bash
python -m wakebot --health-check
```

## 🆘 Troubleshooting

### Ошибка: "No pools collected"

**Причины**:
1. Неверный `QUICKNODE_RPC_URL`
2. Rate limiting
3. Неверный Raydium program ID

**Решение**:
```bash
# Проверьте endpoint
curl -X POST $QUICKNODE_RPC_URL \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"getVersion","params":[]}'
```

### Ошибка: "429 Too Many Requests"

**Причины**: Превышен rate limit

**Решение**:
1. Уменьшите `QUICKNODE_BATCH_SIZE`
2. Увеличьте `LOOP_SECONDS`
3. Улучшите тарифный план QuickNode

### Пулы не проходят фильтры

**Причины**: Слишком строгие фильтры

**Решение**: Скорректируйте параметры:
```bash
FDV_MIN=10000  # Было 50000
FDV_MAX=1000000  # Было 800000
REVIVAL_MIN_AGE_DAYS=3  # Было 7
```

## 🔐 Безопасность

- ✅ API ключи в `.env` (не коммитить!)
- ✅ Rate limiting для защиты от перегрузки
- ✅ Error handling для всех RPC запросов
- ✅ Timeout на все network запросы

## 📚 Дополнительные ресурсы

- [QuickNode Documentation](https://www.quicknode.com/docs)
- [Raydium Developer Docs](https://docs.raydium.io/)
- [Solana Web3.js Guide](https://docs.solana.com/developing/clients/javascript-api)

## ✅ Checklist миграции

- [ ] Получен QuickNode endpoint
- [ ] Настроен `.env` файл
- [ ] Установлен `base58` пакет
- [ ] Пройден `test_quicknode_integration.py`
- [ ] Обновлен `__main__.py` для использования `run_quicknode_cycle`
- [ ] Протестирован на малом количестве циклов
- [ ] Настроены фильтры под ваши требования
- [ ] Настроен Telegram для алертов

## 🎉 Результат

После миграции вы получаете:

✅ **Независимость** от GeckoTerminal API
✅ **Масштабируемость** - мониторинг десятков тысяч пулов
✅ **Скорость** - прямой доступ к blockchain данным
✅ **Гибкость** - полный контроль над фильтрацией и логикой
✅ **Надежность** - нет зависимости от внешних агрегаторов

---

**Вопросы?** Создайте issue в репозитории или обратитесь к документации QuickNode.
