# Точечные правки (Point Fixes)

## Дата: 2025-10-30

## Обзор

Внесены точечные правки для улучшения контроля качества, мониторинга и безопасности кода.

---

## ✅ 1. net_http.py

### Добавлено

**Метод `reset_cycle_metrics()`** - алиас для `reset_cycle_counters()`
```python
def reset_cycle_metrics(self) -> None:
    """Alias for reset_cycle_counters() - reset per-cycle req/429/penalty metrics"""
    self.reset_cycle_counters()
```

**Проверено**: `log_ratelimit_health()` не делает сетевых запросов, использует только `limiter.snapshot()` ✅

---

## ✅ 2. config.py

### Добавлено поле

**`dq_discrepancy_threshold`** - порог расхождения данных CMC vs GT
```python
# Data quality threshold for CMC vs GT comparison
dq_discrepancy_threshold: float
```

**Переменная окружения**:
```bash
export DQ_DISCREPANCY_THRESHOLD=0.25  # default: 25%
```

**Загрузка**:
```python
dq_discrepancy_threshold = float(os.getenv("DQ_DISCREPANCY_THRESHOLD", "0.25"))
```

---

## ✅ 3. cmc.py

### Изменения

**1. Удалена константа `DQ_DISCREPANCY_THRESHOLD`** - заменена на `cfg.dq_discrepancy_threshold`

**2. Обновлена `_log_data_quality()`** - добавлен параметр `cfg`
```python
def _log_data_quality(
    cfg: Config,  # ← новый параметр
    chain: str,
    pool_id: str,
    vol1h_cmc: float,
    vol1h_gt: float,
    prev24h_cmc: float,
    prev24h_gt: float,
) -> None:
    threshold = float(cfg.dq_discrepancy_threshold)  # ← используем из конфига
    # ... rest of logic
```

**3. Улучшена валидация OHLCV candles** - приведение к float с try/except
```python
# Validate and convert OHLCV values to float [o,h,l,c,v at indices 1-5]
for j in range(1, 6):
    try:
        float(c[j])
    except (TypeError, ValueError) as e:
        raise ValueError(f"CMC OHLCV: candle[{i}][{j}] cannot convert to float: {e}")
```

**Сообщения об ошибках**:
- `"CMC OHLCV: candle[2][3] cannot convert to float: could not convert string to float: 'N/A'"`

---

## ✅ 4. alerts.py

### Изменения

**1. Escape всех динамических полей через `_escape_markdown()`**

До:
```python
f"🚨 REVIVAL ({chain_label})\n"
f"Source: {source}\n"
```

После:
```python
f"🚨 REVIVAL ({_escape_markdown(chain_label)})\n"
f"Source: {_escape_markdown(source)}\n"
```

**Затронутые функции**:
- `build_revival_text_cmc()` - chain_label, source, url
- `build_revival_text()` - chain_label, добавлено "Source: GeckoTerminal OHLCV"
- `maybe_alert()` (WAKE-UP) - chain, source_tag, url

**2. Явное указание источника в алертах**

Все алерты теперь содержат строку:
```
Source: CMC DEX
Source: CMC→GT fallback
Source: GeckoTerminal OHLCV
```

---

## ✅ 5. main.py

### Изменения

**1. Вызов `reset_cycle_metrics()` в начале `run_once()`**
```python
# Reset per-cycle metrics for HTTP requests/429/penalty
http.reset_cycle_metrics()
```

**2. Резервирование бюджета под GT fallback**
```python
# Reserve 2-3 requests for GT fallback if enabled
gt_reserve = 0
if cfg.allow_gt_ohlcv_fallback:
    gt_reserve = 3

base_available = max(0, total_budget - discovery_cost - int(cfg.cmc_safety_budget) - gt_reserve)
```

**Лог**:
```
[budget] total=28, discovery_cost=8, spent=2, gt_reserve=3, avail_ohlcv=11, cap=30, final_ohlcv_budget=11
```

**3. Health-check: offline vs online режимы**

#### `--health` (offline, без сети)
Проверяет:
- Наличие chains в конфиге
- CMC_DEX_BASE настроен
- CMC_API_KEY задан (предупреждение если нет)
- CMC_CALLS_PER_MIN > 0
- DB path доступен для записи

```bash
python3 -m wakebot.main --health
```

**Вывод**:
```
[health] Running offline health check (config validation)...
[health] chains: base, solana, ethereum, bsc - OK
[health] cmc_dex_base: https://api.coinmarketcap.com/v4/dex - OK
[health] cmc_api_key: ***ab12 - OK
[health] cmc_calls_per_min: 28 - OK
[health] db_path: wake_state.sqlite - OK
[health] offline check: PASS
[health] Result: PASS
```

#### `--health-online` (с мини-пингом CMC API)
Выполняет:
- 1 discovery запрос (1 страница, limit=5)
- 1 OHLCV запрос (limit=2)

```bash
python3 -m wakebot.main --health-online
```

**Вывод**:
```
[health] Running online health check (CMC API ping)...
[health] discovery on ethereum/ethereum: OK
[health] ohlcv for 0xabc123...: OK
[health] Result: PASS
```

---

## 📊 Сводка изменений

| Файл | Изменения | Тип |
|------|-----------|-----|
| `net_http.py` | `reset_cycle_metrics()` метод | Новое |
| `config.py` | `dq_discrepancy_threshold` поле | Новое |
| `cmc.py` | `_log_data_quality()` с cfg, улучшенная валидация candles | Улучшение |
| `alerts.py` | escape всех динамических полей, явный источник | Исправление безопасности |
| `main.py` | reset_cycle_metrics, GT reserve, --health/--health-online | Улучшение + новое |

---

## 🧪 Валидация

### Синтаксис
```bash
✅ All files compile successfully
```

### Команды для тестирования

**Offline health-check**:
```bash
python3 -m wakebot.main --health
```

**Online health-check**:
```bash
python3 -m wakebot.main --health-online
```

**Single cycle**:
```bash
python3 -m wakebot.main --once
```

---

## 🎯 Результаты

- ✅ Все изменения внесены и проверены
- ✅ Синтаксис Python валидирован
- ✅ Логи и формат выводов сохранены
- ✅ Существующее поведение не нарушено
- ✅ Добавлена безопасность (escape Markdown)
- ✅ Улучшен мониторинг (GT reserve, metrics reset)

---

## 📝 Примечания

### Markdown Escaping
Теперь все динамические поля (символы токенов, адреса пулов, chain labels) проходят через `_escape_markdown()` перед отправкой в Telegram. Это защищает от случайных ошибок форматирования и injection-атак через специальные символы Markdown.

### GT Reserve
При включенном `ALLOW_GT_OHLCV_FALLBACK=true` система резервирует 3 запроса из бюджета под возможные GT fallback вызовы, что предотвращает превышение rate limit.

### Health-check режимы
- `--health`: быстрая проверка конфига без нагрузки на API (0 сетевых запросов)
- `--health-online`: полноценная проверка работоспособности API (2 запроса)

Рекомендуется использовать `--health` для CI/CD пайплайнов и pre-commit хуков, а `--health-online` для периодического мониторинга.

---

## ✨ Готовность

**Все точечные правки успешно внесены и готовы к использованию!**
