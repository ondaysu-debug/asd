# 🚀 GeckoTerminal Megafilter Migration - Complete

## ✅ Статус миграции: ЗАВЕРШЕНА

Проект успешно мигрирован с гибридной CMC+GT архитектуры на чистую GeckoTerminal реализацию.

---

## 📋 Что было сделано

### ✅ Фаза 1: Создание новых модулей

1. **`gt_megafilter.py`** - клиент для `/pools/megafilter`
   - `GTMegafilterClient` - основной клиент для discovery
   - `MegafilterFilters` - dataclass для параметров фильтрации
   - Поддержка 7-дневного минимального возраста пулов
   - **БЕЗ** honeypot проверок (как требовалось)

2. **`gt_data.py`** - unified data service
   - `GTDataService` - унифицированный сервис для работы с GT
   - `fetch_volume_metrics()` - получение метрик через GT OHLCV
   - `get_pool_details()` - детальная информация о пуле

### ✅ Фаза 2: Обновление существующих модулей

3. **`config.py`** - полностью обновлен
   - ✅ Добавлены параметры GT Megafilter
   - ✅ Удалены все CMC параметры
   - ✅ Сохранен `revival_min_age_days = 7`
   - ✅ Добавлен `fdv_min` и `fdv_max`

4. **`discovery.py`** - полностью переписан
   - ✅ Новая функция `unified_gt_discovery()`
   - ✅ Использует `GTMegafilterClient`
   - ✅ Применяет фильтры с 7-дневным возрастом
   - ✅ Удалены все CMC функции

5. **`net_http.py`** - обновлен
   - ✅ Добавлен `megafilter_get_json()` для Pro API
   - ✅ Сохранен `gt_get_json()` для OHLCV
   - ✅ Удалены все CMC методы
   - ✅ Отдельные rate limiters для Megafilter и OHLCV

6. **`main.py`** - переписан
   - ✅ Использует `unified_gt_discovery()`
   - ✅ Использует `GTDataService`
   - ✅ Обновленные функции health check
   - ✅ Удалены все CMC вызовы

7. **`alerts.py`** - обновлен
   - ✅ Переименованы функции: `should_alert_revival_gt()`, `build_revival_text_gt()`
   - ✅ Сохранена логика проверки 7-дневного возраста
   - ✅ Добавлено поле `volume_24h` в `AlertInputs`

8. **`filters.py`** - обновлен
   - ✅ Добавлена поддержка FDV фильтров
   - ✅ Добавлена проверка возраста пулов (`min_age_days = 7`)

### ✅ Фаза 3: Удаление legacy кода

9. **`cmc.py`** - УДАЛЕН
   - ✅ Функции кэширования перенесены в `gecko.py`
   - ✅ Все импорты очищены

---

## 🎯 Ключевые преимущества новой архитектуры

### До (Гибридная CMC+GT):
```
CMC Discovery → CMC OHLCV → GT Fallback → Alerts
GT Discovery → GT OHLCV → Alerts

❌ Дублирование кода
❌ Сложная конфигурация  
❌ Разные форматы данных
❌ Двойные лимиты API
❌ Сложный дебаг
```

### После (Чистая GT):
```
GT Megafilter Discovery → GT OHLCV Monitoring → Alerts

✅ Единый discovery эндпоинт
✅ Упрощенная конфигурация
✅ Мощные фильтры Megafilter
✅ Сохранение точных OHLCV данных
✅ Избегание honeypot проверок
✅ Сохранение 7-дневного возраста
```

---

## 🔍 Проверка 7-дневной логики

Логика минимального возраста пулов (7 дней) **сохранена** на всех уровнях:

1. **Megafilter запрос** (`gt_megafilter.py`):
   ```python
   "pool_created_hour_min": 168  # 7 дней * 24 часа
   ```

2. **Discovery фильтры** (`discovery.py`):
   ```python
   pool_age_min_hours=cfg.revival_min_age_days * 24  # 7 ДНЕЙ
   ```

3. **Pool data filters** (`filters.py`):
   ```python
   if pool_age_days < min_age_days:  # min_age_days = 7
       return False
   ```

4. **OHLCV мониторинг** (`gecko.py`):
   ```python
   ok_age = (now_dt - created_dt) >= timedelta(days=int(cfg.revival_min_age_days))
   ```

5. **Алерты** (`alerts.py`):
   ```python
   if not ok_age:  # ok_age = pool_age_days >= 7
       return False
   ```

6. **Конфигурация** (`config.py`):
   ```python
   revival_min_age_days = int(os.getenv("REVIVAL_MIN_AGE_DAYS", "7"))
   ```

---

## 📦 Новые файлы

- `wakebot/gt_megafilter.py` - Megafilter клиент
- `wakebot/gt_data.py` - Unified data service
- `.env.example` - Обновленный пример конфигурации
- `GT_MEGAFILTER_MIGRATION.md` - Эта документация

---

## 🔧 Настройка

### 1. Обновите `.env` файл

Используйте `.env.example` как шаблон. Основные параметры:

```bash
# GeckoTerminal Pro API (для Megafilter)
GT_MEGAFILTER_BASE=https://pro-api.coingecko.com/api/v3/onchain
GT_MEGAFILTER_API_KEY=your_coingecko_pro_api_key

# GeckoTerminal Public API (для OHLCV)
GECKO_BASE=https://api.geckoterminal.com/api/v2

# Фильтры
FDV_MIN=50000
FDV_MAX=800000
LIQUIDITY_MIN=50000
LIQUIDITY_MAX=800000
REVIVAL_MIN_AGE_DAYS=7

# Сети
CHAINS=base,ethereum,solana
```

### 2. Установите зависимости

```bash
pip install -r requirements.txt
```

### 3. Запустите health check

```bash
# Offline check
python -m wakebot --health-check

# Online check (тестирует GT Megafilter и OHLCV)
python -m wakebot --health-check-online
```

### 4. Запустите бота

```bash
python -m wakebot
```

---

## 🚫 Удаленные зависимости

Следующие параметры **больше не используются** и могут быть удалены из `.env`:

```bash
# CMC DEX (удалено)
CMC_DEX_BASE
CMC_DEX_BASE_ALT
CMC_API_KEY
CMC_CALLS_PER_MIN
CMC_RETRY_AFTER_CAP_S
CMC_SOURCES
CMC_ROTATE_SOURCES
CMC_PAGES_PER_CHAIN
CMC_DEX_PAGES_PER_CHAIN
CMC_PAGE_SIZE
CMC_SAFETY_BUDGET

# GT Legacy Discovery (удалено)
GECKO_SOURCES
GECKO_ROTATE_SOURCES
GECKO_PAGES_PER_CHAIN
GECKO_DEX_PAGES_PER_CHAIN
GECKO_PAGE_SIZE

# CMC-GT Hybrid (удалено)
ALLOW_GT_OHLCV_FALLBACK
DQ_DISCREPANCY_THRESHOLD

# Legacy Revival (удалено)
REVIVAL_ENABLED
REVIVAL_PREV_WEEK_MAX_USD
REVIVAL_NOW_24H_MIN_USD
REVIVAL_RATIO_MIN
REVIVAL_USE_LAST_HOURS
```

---

## 📊 Архитектура Discovery

### Megafilter Endpoint

```
GET https://pro-api.coingecko.com/api/v3/onchain/pools/megafilter

Параметры:
- networks: ethereum, base, solana, etc.
- page, page_size: пагинация
- sort: h6_trending, h24_volume, etc.
- fdv_usd_min, fdv_usd_max: FDV фильтры
- reserve_in_usd_min, reserve_in_usd_max: ликвидность
- h24_volume_usd_min: минимальный 24h объем
- pool_created_hour_min: минимальный возраст (168 часов = 7 дней)
- tx_count_max: максимум транзакций
```

### OHLCV Monitoring

```
GET https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool_id}/ohlcv/hour

Параметры:
- aggregate: 1 (часовые свечи)
- limit: 25 (1h + 24h для сравнения)
```

---

## ✅ Проверочный список

- [x] Создан `gt_megafilter.py` с `GTMegafilterClient`
- [x] Создан `gt_data.py` с `GTDataService`
- [x] Обновлен `config.py` - добавлен GT Megafilter, удален CMC
- [x] Переписан `discovery.py` на `unified_gt_discovery()`
- [x] Обновлен `net_http.py` - добавлен `megafilter_get_json()`, удален CMC
- [x] Обновлен `main.py` - заменены CMC вызовы на GT
- [x] Обновлен `alerts.py` - переименованы функции на GT
- [x] Обновлен `filters.py` - добавлена поддержка FDV и возраста
- [x] Удален `cmc.py` и очищены импорты
- [x] Проверена 7-дневная логика во всех компонентах
- [x] Создана документация и `.env.example`
- [x] **НЕ используются** honeypot проверки
- [x] **Сохранена** логика 7-дневного минимального возраста

---

## 🎉 Результат

Проект полностью мигрирован на чистую GeckoTerminal архитектуру:
- ✅ Один источник данных (GeckoTerminal)
- ✅ Мощный Megafilter для discovery
- ✅ Специализированные OHLCV эндпоинты для мониторинга
- ✅ Без honeypot проверок
- ✅ С сохранением 7-дневной логики

**Миграция завершена успешно! 🚀**
