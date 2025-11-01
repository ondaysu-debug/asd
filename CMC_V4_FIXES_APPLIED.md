# Исправления для CMC API v4 - Применены

## Дата применения: 2025-11-01

## Исправленные файлы

### 1. `wakebot/discovery.py`

#### Функция `_validate_cmc_pairs_doc()`
- ✅ **Исправлена обработка error_code как строки "0"**
  - Теперь проверяется `str(error_code) != "0"` вместо `error_code != 0`
  - Добавлено логирование успешных ответов для отладки
- ✅ **Добавлен диагностический вывод структуры данных**
  - Выводится пример первого элемента для понимания структуры
  - Показываются ключевые поля: name, network_slug, символы токенов, quote type

#### Функция `_extract_common_fields()`
- ✅ **Полностью переписана для CMC v4 формата**
  - Извлечение токенов напрямую из полей `base_asset_*` и `quote_asset_*`
  - Удалена зависимость от старой функции `_extract_token()`
- ✅ **Обработка quote как массива**
  - Поиск USD quote (convert_id == "2781")
  - Fallback на первый доступный quote
  - Извлечение liquidity и volume_24h из правильного элемента
- ✅ **Ослабление требований к идентификаторам**
  - Достаточно иметь либо symbol, либо address для токена
  - Проверка: `if not (base_tok["symbol"] or base_tok["address"])...`
- ✅ **Оценка tx24h из volume_24h**
  - Используется формула: `tx24h = max(1, int(volume_24h / 1000))`
  - Предполагается средний размер сделки $1000

#### Функция `_fetch_page()` внутри `cmc_discover_by_source()`
- ✅ **Регистронезависимое сравнение network_slug**
  - `pool_network_slug = str(pool.get("network_slug", "")).lower()`
  - `expected_network_slug = str(cmc_chain).lower()`
- ✅ **Правильная обработка scroll_id из status**
  - `scroll_id = status.get("scroll_id")`
  - Возврат scroll_id даже при отсутствии данных
- ✅ **Диагностический вывод**
  - Логирование error_code и elapsed из status
  - Вывод обрабатываемых пар: `{symbol}/{symbol} liq=$...`
  - Количество найденных кандидатов на каждой странице
- ✅ **Извлечение volume_24h из quote array**
  - Поиск USD quote и извлечение volume_24h
  - Добавление к результату для сортировки
- ✅ **Улучшенная обработка ошибок**
  - Добавлен traceback.print_exc() для детальной диагностики

#### Логика пагинации
- ✅ **Scroll-based пагинация вместо номеров страниц**
  - URL строится с параметром `&scroll_id={scroll_id}`
  - Цикл: `while pages_iterated < pages_planned`
- ✅ **Предотвращение бесконечных циклов**
  - Проверка: `if not next_scroll_id or next_scroll_id == scroll_id: break`
  - Отслеживание изменения scroll_id
- ✅ **Добавление параметра category**
  - `if category != "all": base_url += f"&category={category}"`
  - Применяется для всех блоков пагинации (new/trending/dexes/else)

#### Удаление неиспользуемого кода
- ✅ **Удалена функция `_extract_token()`**
  - Больше не используется после переписывания `_extract_common_fields()`

#### Финальная статистика
- ✅ **Добавлен вывод результатов**
  - `print(f"[discover][{chain}] Final: {len(result)} unique candidates from {scanned_pairs} scanned pairs")`

---

### 2. `wakebot/filters.py`

#### Функция `is_token_native_pair()`
- ✅ **Более надежное сравнение токенов**
  - Проверка адресов (первичная)
  - Fallback на проверку символов
- ✅ **Нормализация символов**
  - `b_symbol = (base_token.get("symbol") or "").upper()`
  - `q_symbol = (quote_token.get("symbol") or "").upper()`
  - `native_symbols = {s.upper() for s in NATIVE_SYMBOLS.get(chain, set())}`
- ✅ **Двухуровневая проверка**
  1. Сначала по адресам (наиболее надежно)
  2. Затем по символам (fallback)
- ✅ **Улучшенная документация**
  - Добавлен комментарий FIX для ясности изменений

---

## Ключевые улучшения

### 1. Обработка API ответов
- ✅ error_code как строка "0" == успех
- ✅ Детальное логирование status
- ✅ Диагностический вывод структуры данных

### 2. Извлечение данных токенов
- ✅ Прямое извлечение из CMC v4 полей
- ✅ quote как массив с поиском USD
- ✅ Расслабленные требования к идентификаторам

### 3. Пагинация
- ✅ Scroll-based вместо page numbers
- ✅ Защита от бесконечных циклов
- ✅ Правильная передача scroll_id

### 4. Фильтрация токенов
- ✅ Case-insensitive network_slug
- ✅ Fallback на символы при отсутствии адресов
- ✅ Улучшенная обработка нативных токенов

---

## Результаты тестирования

### Тесты пройдены успешно ✅
```
tests/test_alerts.py::test_should_alert_rule_edges PASSED
tests/test_alerts.py::test_maybe_alert_with_gecko_then_cooldown PASSED
tests/test_alerts.py::test_maybe_alert_no_alert_when_zero_window PASSED
tests/test_filters.py::test_normalize_address_evm_lowercases PASSED
tests/test_filters.py::test_is_token_native_pair_detection PASSED
tests/test_filters.py::test_is_base_token_acceptable_filters_majors_and_natives PASSED
tests/test_filters.py::test_pool_data_filters_range PASSED
tests/test_gecko_cache.py::test_gecko_ttl_cache_avoids_repeat_calls PASSED
tests/test_rate_limit.py::test_token_bucket_limits_throughput PASSED
tests/test_rate_limit.py::test_adaptive_decrease_and_recover PASSED

10 passed in 1.10s
```

### Проверка синтаксиса ✅
- Файлы скомпилированы без ошибок

---

## Примечания

1. **Backward compatibility**: Изменения совместимы с существующими тестами
2. **Verbose logging**: Добавлено детальное логирование для отладки
3. **Robust error handling**: Улучшена обработка ошибок с traceback
4. **Flexible data extraction**: Код более устойчив к вариациям в структуре данных

---

## Следующие шаги

1. Протестировать с реальным CMC API
2. Проверить работу с разными chains
3. Мониторить логи на предмет новых проблем
4. При необходимости добавить дополнительные fallback механизмы
