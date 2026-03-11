# Selfhosted Assistant Index

Этот файл нужен как быстрый вход в репозиторий для LLM-агентов и разработчиков.

## Сначала прочитать
- `README.md` - продуктовая цель, переменные окружения, запуск, research flow.
- `llm_routing_config.json` - активный LLM-провайдер, модель, policy и whitelist MCP.
- `.vscode/mcp.json` - локальная конфигурация Tavily MCP для VS Code.
- `scripts/run_tests.py` - именованные test suites и способ локального прогона.

## Точки входа
- `main.py` - запуск приложения.
- `telegram_bot.py` - Telegram transport, команды и входящие сообщения.
- `chat_application_service.py` - основная orchestration-логика чата и сессий.
- `research_service.py` - research flow, контекст и follow-up запросы.

## Индексы по директориям
- `.github/claude.md` - skill-документация и вложенные индексы.
- `.vscode/claude.md` - workspace-конфиги VS Code, MCP и задачи.
- `integrations/claude.md` - внешние LLM adapters и provider-слой.
- `llm_core/claude.md` - контракты, router, gateway и policy.
- `llm_inference/claude.md` - локальный inference и privacy helpers.
- `scripts/claude.md` - служебные и smoke-скрипты.
- `tests/claude.md` - покрытие тестами и где искать нужный сценарий.

## Важные root-файлы
- `assistant_service.py` - orchestration прикладной логики вокруг assistant flow.
- `request_classifier.py` - LLM-классификация запросов.
- `intent_classifier.py` - declarative intent classification через registry-конфиг.
- `capability_registry.py` и `capability_registry.json` - source of truth для capability/intent routing.
- `google_calendar_client.py` - интеграция с Google Calendar и Google Tasks.
- `voice_service.py` и `voice_input_service.py` - voice/audio pipeline.
- `research_context_store.py` - сохранение research-контекста между сообщениями.
- `models.py` - общие модели данных.
- `logger.py` и `utils.py` - инфраструктурные утилиты.

## Не индексируем как рабочие директории
- `.git/`, `.venv/`, любые `__pycache__/` - служебные или сгенерированные каталоги.