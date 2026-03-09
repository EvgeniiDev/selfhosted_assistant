# LLM Core Index

Этот каталог описывает внутренний контрактный и orchestration-слой LLM.

## Файлы
- `contracts.py` - базовые типы запросов, ответов и provider interface.
- `router.py` - выбор provider/model по task type и конфигурации.
- `gateway.py` - общий вход в LLM pipeline для application-слоя.
- `policy.py` - guardrails: `text_only`, whitelist MCP и policy decision.
- `__init__.py` - пакетный маркер.

## Когда читать
- Нужно понять, как запрос проходит путь от handler-а до конкретного provider.
- Нужно изменить маршрутизацию моделей или применяемые policy.
- Нужно добавить новый provider без утечки provider-specific логики в application layer.