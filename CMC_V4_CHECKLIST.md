# CMC DEX API v4 - Чек-лист проверки

## ✅ Все изменения выполнены

### 1. config.py
- [x] CMC_DEX_BASE = `https://pro-api.coinmarketcap.com/v4/dex`
- [x] CMC_DEX_BASE_ALT = `None` (отключен)
- [x] chain_slugs: `bsc → bnb`
- [x] DQ_DISCREPANCY_THRESHOLD из ENV (default 0.25)

### 2. net_http.py
- [x] Всегда добавляется заголовок `X-CMC_PRO_API_KEY`
- [x] Удалена ALT retry логика на api.coinmarketcap.com
- [x] Сохранены лимитер, Retry-After, счётчики 429

### 3. discovery.py
- [x] Discovery URL всегда содержит `category=new|trending|all`
- [x] Формат: `/spot-pairs/latest?chain_slug={chain}&category={cat}&page={p}&limit={l}`
- [x] Маппинг: new→new, trending→trending, остальное→all
- [x] Удалён перебор альтернативных slug'ов
- [x] Логи прогресса: `[discover][{chain}] pages: {done}/{planned}...`

### 4. cmc.py
- [x] OHLCV endpoint v4: `/pairs/ohlcv/latest?chain_slug={ch}&pair_address={id}&timeframe=1h&aggregate=1&limit=25`
- [x] Строгая валидация `_validate_cmc_ohlcv_doc()`
- [x] GT fallback при сбое (если allow_gt_ohlcv_fallback=true)
- [x] Data-quality логи при CMC→GT fallback
- [x] Возвращает source tag: `(vol1h, prev24h, ok_age, source)`

### 5. alerts.py
- [x] Явно указывается Source: "CMC DEX" / "CMC→GT fallback"
- [x] Все динамические поля экранируются через `_escape_markdown()`

### 6. main.py
- [x] `reset_cycle_metrics()` в начале `run_once()`
- [x] Резерв бюджета под GT-фолбэк
- [x] `--health` режим (офлайн проверка)
- [x] `--health-online` режим (с debug URL)

### 7. Запуск пакета
- [x] `python -m wakebot` работает
- [x] `python -m wakebot.main --once` работает
- [x] `python -m wakebot.main --health` работает
- [x] `python -m wakebot.main --health-online` работает

## Проверка работоспособности

### Шаг 1: Установить зависимости
```bash
pip install -r requirements.txt
```

### Шаг 2: Офлайн проверка
```bash
python3 -m wakebot.main --health
```
Ожидается: `[health] offline check: PASS`

### Шаг 3: Запуск тестов
```bash
python3 -m pytest tests/ -v
```
Ожидается: `10 passed`

### Шаг 4: Проверка URL (без API ключа)
```bash
python3 -m wakebot.main --once 2>&1 | grep "chain_slug"
```
Ожидается в логах:
```
https://pro-api.coinmarketcap.com/v4/dex/spot-pairs/latest?chain_slug=ethereum&category=new&page=...
```
НЕ должно быть:
```
https://api.coinmarketcap.com/...  # старый хост
```

### Шаг 5: С API ключом (если доступен)
```bash
export CMC_API_KEY=your_key_here
python3 -m wakebot.main --health-online
```
Ожидается: вывод debug URL с category + результат проверки

### Шаг 6: Полный цикл с BSC
```bash
export CMC_API_KEY=your_key_here
export CHAINS=base,solana,ethereum,bsc
export CMC_SOURCES=new,trending
python3 -m wakebot.main --once 2>&1 | grep -E "\[discover\]|\[cycle\]"
```
Проверить в логах:
- `[discover][bsc]` есть в выводе (BSC обрабатывается)
- URL содержит `chain_slug=bnb` (BSC правильно маппится)
- URL содержит `category=new` или `category=trending`

## Критичные точки проверки

### ❌ НЕ ДОЛЖНО БЫТЬ:
1. Запросов на `https://api.coinmarketcap.com/...`
2. URL без параметра `category`
3. Ошибок 400 из-за отсутствия category
4. Попыток retry на ALT хост при 404

### ✅ ДОЛЖНО БЫТЬ:
1. Только `https://pro-api.coinmarketcap.com/v4/dex/...`
2. Каждый discovery URL содержит `category=new|trending|all`
3. OHLCV URL: `timeframe=1h&aggregate=1&limit=25`
4. Логи: `[discover][{chain}] pages: ...`
5. Логи: `[rate] req=... 429=... penalty=...`
6. Логи: `[rl:cmc] rps=... tokens=... p429%=...`

## Пример правильных URL

### Discovery (new)
```
https://pro-api.coinmarketcap.com/v4/dex/spot-pairs/latest?chain_slug=bnb&category=new&page=1&limit=100
```

### Discovery (trending)
```
https://pro-api.coinmarketcap.com/v4/dex/spot-pairs/latest?chain_slug=ethereum&category=trending&page=1&limit=100
```

### OHLCV
```
https://pro-api.coinmarketcap.com/v4/dex/pairs/ohlcv/latest?chain_slug=base&pair_address=0xABC123&timeframe=1h&aggregate=1&limit=25
```

## Переменные окружения

Основные:
```bash
CMC_API_KEY=your_key_here          # Обязательно для работы
CHAINS=base,solana,ethereum,bsc    # Список сетей
CMC_SOURCES=new,trending           # Источники discovery
DQ_DISCREPANCY_THRESHOLD=0.25      # Порог data-quality проверки
ALLOW_GT_OHLCV_FALLBACK=false      # Fallback на GeckoTerminal
```

Полный список см. в `config.py`

## Дополнительная информация

- Все изменения минимально-инвазивные
- Бизнес-логика (seen, budget, alerts) не тронута
- Обратная совместимость с тестами сохранена
- Готово к продакшену с валидным CMC_API_KEY
