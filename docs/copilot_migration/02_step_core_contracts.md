# Шаг 1: LLM Core контракты и конфиг

## Цель
Создать устойчивый слой абстракции над LLM-провайдерами, чтобы application-код не зависел от конкретной интеграции.

## Что реализовать
1. Добавить пакет `llm_core/`:
- `contracts.py`
- `gateway.py`
- `router.py`
2. Описать контракты:
- `LLMRequest`
- `LLMResponse`
- `LLMProvider` (protocol/interface)
3. Добавить конфиг маршрутизации:
- `llm_routing_config.json`

## Правила
1. Контракты должны быть provider-agnostic.
2. В контрактах не должно быть Telegram-специфики.
3. Типы полей и структура должны покрывать:
- task type
- metadata
- policy flags (`text_only`, `allow_mcp_tools`)
- usage и trace данные

## Критерии успешности
1. `gateway` принимает `LLMRequest` и возвращает `LLMResponse`.
2. Router может выбрать провайдер по конфигу (`copilot` как active).
3. Ни один application-файл пока не обязан импортировать интеграции напрямую.

## Проверка
1. Импорт модулей без ошибок:
```bash
python -c "from llm_core.contracts import LLMRequest, LLMResponse; print('ok')"
```
2. Router возвращает активный провайдер из конфига.
3. Документация по контрактам описана в docstrings.

## Риски
1. Слишком узкий контракт усложнит добавление новых провайдеров.
2. Слишком широкий контракт усложнит сопровождение.

## Решение рисков
1. Добавлять только поля, реально нужные этапу 1.
2. Расширяемость обеспечивать через `metadata`/`raw_meta`.
