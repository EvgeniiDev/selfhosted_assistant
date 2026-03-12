# Scripts Index

Служебные скрипты для проверки интеграций, запуска тестов и локальной диагностики.

## Файлы
- `run_tests.py` - именованные наборы тестов: `fast`, `non-telegram`, `real-copilot`, `all`.
- `list_tasklists.py` - утилита для просмотра доступных Google Tasks tasklist-ов.
- `smoke_copilot_provider.py` - быстрый smoke для Copilot provider.
- `smoke_policy_guardrails.py` - проверка policy/guardrails без полного приложения.
- `smoke_research_skill.py` - smoke research pipeline и Copilot skill integration.
- `export_channels.py` - выгрузка постов из публичных Telegram-каналов за N дней в JSONL для RAG (без API-ключей, через t.me/s/).
  Запуск: `.venv\\Scripts\\python.exe scripts/export_channels.py --days 7 --output channel_export.jsonl`

## Когда использовать
- Перед изменениями в LLM routing, provider session management или research flow.
- Для быстрой локальной проверки без запуска полного Telegram-бота.

## Важно
- Скрипты должны уметь импортировать локальные пакеты через project root в `sys.path`.