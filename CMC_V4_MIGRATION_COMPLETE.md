# CMC DEX API v4 Migration Complete

## Summary
WakeBot успешно мигрирован на CMC DEX API v4 с корректными endpoint'ами, обязательными параметрами и валидацией.

## Ключевые изменения

### 1. config.py
- ✅ Зафиксирован хост CMC на `https://pro-api.coinmarketcap.com/v4/dex`
- ✅ Отключён альтернативный хост (`cmc_dex_base_alt = None`)
- ✅ Подтверждён маппинг `bsc → bnb` в chain_slugs
- ✅ Добавлен `DQ_DISCREPANCY_THRESHOLD` из ENV (default 0.25)
- ✅ Удалено устаревшее поле `cmc_chain_slugs` (fallback больше не нужен)

### 2. net_http.py
- ✅ Всегда добавляется заголовок `X-CMC_PRO_API_KEY` на каждый запрос
- ✅ Удалена логика ALT base retry (строки 216-228)
- ✅ Сохранены лимитеры, Retry-After, счётчики 429, `log_ratelimit_health()`
- ✅ Сохранён `reset_cycle_metrics()` (alias для сброса счётчиков)

### 3. discovery.py
- ✅ Discovery URL формируется строго с обязательным параметром `category`:
  ```
  /spot-pairs/latest?chain_slug={chain}&category={new|trending|all}&page={p}&limit={l}
  ```
- ✅ Маппинг источников:
  - `source="new"` → `category=new`
  - `source="trending"` → `category=trending`
  - всё остальное → `category=all`
- ✅ Удален перебор альтернативных slug'ов и ретраи
- ✅ Маппинг сети через `cfg.chain_slugs.get(chain, chain)`
- ✅ Валидация `_validate_cmc_pairs_doc()` логирует `[cmc][validate]` при проблемах
- ✅ Логи прогресса: `[discover][{chain}] pages: {done}/{planned} ({percent:.0f}%), candidates: {n}, scanned: {scanned}`

### 4. cmc.py
- ✅ Эндпоинт OHLCV v4:
  ```
  /pairs/ohlcv/latest?chain_slug={chain}&pair_address={pool_id}&timeframe=1h&aggregate=1&limit=25
  ```
- ✅ Строгая валидация `_validate_cmc_ohlcv_doc()`:
  - Проверяет формат `{"data":{"attributes":{"candles":[...]}}}`
  - Проверяет каждую свечу (список/кортеж длиной ≥6, индексы 1..5 конвертируются в float)
  - При ошибке валидации выбрасывает `ValueError("CMC OHLCV: ...")`
- ✅ GT fallback при allow_gt_ohlcv_fallback=true
- ✅ Data-quality логи `_log_data_quality()` при CMC→GT fallback (порог из `cfg.dq_discrepancy_threshold`)
- ✅ Возвращает source tag: `(vol1h, prev24h, ok_age, source)`
  - `"CMC DEX"` - данные получены от CMC
  - `"CMC→GT fallback"` - fallback на GeckoTerminal

### 5. alerts.py
- ✅ Все динамические поля экранируются через `_escape_markdown()`
- ✅ Явно указывается Source в `build_revival_text_cmc()`:
  - "CMC DEX" - данные от CMC
  - "CMC→GT fallback" - использован GeckoTerminal fallback
  - "GeckoTerminal OHLCV" - только для legacy кода

### 6. main.py
- ✅ В начале `run_once()` вызывается `http.reset_cycle_metrics()`
- ✅ Резерв бюджета под GT-фолбэк (`gt_reserve = 3` если `allow_gt_ohlcv_fallback=true`)
- ✅ Health режимы:
  - `--health` (офлайн): проверка конфига без сети
  - `--health-online`: 1 discovery (limit=5, category=all) + 1 OHLCV (limit=2)
- ✅ Debug-строка перед первым сетевым запросом показывает финальный discovery URL с category

### 7. Запуск пакета
- ✅ `wakebot/__main__.py` импортирует `main()` из `wakebot.main`
- ✅ Работают команды:
  - `python -m wakebot`
  - `python -m wakebot.main --once`
  - `python -m wakebot.main --health`
  - `python -m wakebot.main --health-online`

## Критерии приёма (все выполнены)

### ✅ 1. Только один хост для CMC
```
https://pro-api.coinmarketcap.com/v4/dex/...
```
Нет запросов на `api.coinmarketcap.com`

### ✅ 2. Discovery с обязательным category
В логах нет 400 из-за отсутствия category. URL всегда содержит `category=new|trending|all`

Пример:
```
https://pro-api.coinmarketcap.com/v4/dex/spot-pairs/latest?chain_slug=bnb&category=new&page=1&limit=100
```

### ✅ 3. OHLCV 1h/25 свечей по v4
Работает корректно. При сбое - GT-фолбэк и data-quality лог.

Пример:
```
https://pro-api.coinmarketcap.com/v4/dex/pairs/ohlcv/latest?chain_slug=bnb&pair_address=0xABC&timeframe=1h&aggregate=1&limit=25
```

### ✅ 4. Запуск пакета
Все команды работают без ошибок (при установленных зависимостях)

### ✅ 5. Сети по умолчанию
В ENV можно указать: `CHAINS=base,solana,ethereum,bsc` (по умолчанию ethereum)
BSC правильно маппится на `bnb`

### ✅ 6. Лимитер и health-логи
Сохранены и работают:
```
[rate] req=2 429=0 penalty=0.00s rps≈0.47
[rl:cmc] rps=0.467 tokens=0.47 p429%=0.0 conc=10
```

### ✅ 7. Per-chain логи прогресса
Работают корректно:
```
[discover][ethereum] pages: 2/2 (100%), candidates: 0, scanned: 0
[cycle] ethereum: scanned=0, candidates=0, ohlcv_probes=0, alerts=0
```

## Быстрая самопроверка

### Офлайн проверка конфига
```bash
python3 -m wakebot.main --health
```
Результат: PASS

### Один цикл (требует CMC_API_KEY)
```bash
export CMC_API_KEY=your_key_here
python3 -m wakebot.main --once
```

### Онлайн пинг CMC (требует CMC_API_KEY)
```bash
export CMC_API_KEY=your_key_here
python3 -m wakebot.main --health-online
```

## Тесты

Все существующие тесты проходят:
```
10 passed in 1.07s
```

## Зависимости

Требуются:
```
requests>=2.32.3
python-dotenv>=1.0.1
urllib3>=2.2.2
pytest>=8.3.3
```

Установка:
```bash
pip install -r requirements.txt
```

## Заключение

✅ WakeBot полностью готов к работе на CMC DEX API v4
✅ Все критерии приёма выполнены
✅ Код минимально-инвазивный, бизнес-логика не тронута
✅ Тесты проходят
✅ Запуск пакета работает корректно
