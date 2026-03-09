# Self-Hosted Telegram Assistant (Calendar + Tasks + Notes + Voice)

Telegram-ассистент, который:

- классифицирует входящие запросы (`calendar_event`, `task`, `note`, `unknown`),
- создает события в Google Calendar,
- создает задачи в Google Tasks,
- сохраняет заметки,
- распознает голосовые и аудио через GigaAM.

## Архитектура LLM (этап 1 миграции)

Реализовано разделение на слои:

- `Application`: Telegram flow и бизнес-логика обработчиков.
- `LLM Core`: `llm_core/contracts.py`, `llm_core/router.py`, `llm_core/gateway.py`, `llm_core/policy.py`.
- `Integrations`: `integrations/copilot_sdk/provider.py`.

Текущее поведение:

- активный провайдер задается в `llm_routing_config.json` (`copilot` по умолчанию),
- pipeline обработчиков идет через `LLMGateway`,
- policy-layer применяет `text_only` и whitelist для MCP,
- в логах фиксируются route/policy/usage.

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Переменные окружения

Обязательные:

- `TELEGRAM_BOT_TOKEN`
- `GOOGLE_OAUTH_TOKEN_V2` (или интерактивная первичная OAuth-настройка)

Google/бот:

- `TELEGRAM_ALLOWED_USERS`
- `GOOGLE_CREDENTIALS_PATH`
- `GOOGLE_OAUTH_TOKEN`
- `GOOGLE_OAUTH_CLIENT_CONFIG`
- `GOOGLE_TASKLIST_ID`
- `TIMEZONE`

LLM:

- `COPILOT_MODEL` (опционально, модель по умолчанию для Copilot SDK; default `gpt-4.1`)
- `COPILOT_SKILL_DIRS` (опционально; список директорий skills через `;`, default `.github/skills`)
- `COPILOT_DISABLED_SKILLS` (опционально; список skill id через `,`)
- `COPILOT_WORKING_DIRECTORY` (опционально; рабочая директория сессии Copilot)
- `TAVILY_API_KEY` (обязательно для research через Tavily MCP)
- `TAVILY_DEFAULT_PARAMETERS` (опционально; JSON-строка c дефолтными параметрами Tavily MCP, например `{"max_results":5,"search_depth":"advanced"}`)

Research mode:

- `RESEARCH_CONTEXT_DIR` (опционально; директория кэша research-сессий, по умолчанию `%TEMP%/selfhosted_assistant/research`)

Copilot SDK auth (recommended):

1. Выполнить `gh auth login -h github.com -w`
2. Проверить `gh auth status -h github.com`
3. Токен из `gh auth` используется SDK напрямую (PAT `github_pat_*` для этого потока не нужен)

Voice:

- `GIGAAM_MODEL_NAME`
- `HF_TOKEN` (для некоторых longform сценариев)

## Конфигурация роутинга и policy

Файл: `llm_routing_config.json`

- `active_provider`: основной провайдер (`copilot`)
- `providers`: модельные профили и task-type маршрутизация
- `policies.text_only`: включает guardrails против write/shell действий
- `policies.allow_mcp_tools`: разрешение MCP-инструментов
- `policies.allowed_mcp_servers`: whitelist MCP серверов

## Tavily MCP

Research flow теперь реально подключает Tavily MCP к Copilot SDK session, если задан `TAVILY_API_KEY`.

Что используется:

- workspace-конфиг VS Code: `.vscode/mcp.json`
- runtime-конфиг Copilot SDK: `integrations/copilot_sdk/provider.py`
- research-запросы явно маркируются как `mcp_server=tavily`

Требования:

- установлен `Node.js` с доступным `npx`
- задан `TAVILY_API_KEY`
- выполнен `gh auth login -h github.com -w`

Как это работает:

- VS Code видит сервер `tavily` через `.vscode/mcp.json`
- Python provider добавляет `mcp_servers["tavily"]` в `SessionConfig`
- сервер запускается командой `npx -y tavily-mcp@latest`
- при наличии `TAVILY_DEFAULT_PARAMETERS` они пробрасываются в `DEFAULT_PARAMETERS`

Быстрая проверка:

```bash
.venv\Scripts\python.exe scripts\smoke_research_skill.py --prompt "Исследуй тему retrieval augmented generation"
```

Если нужен визуальный статус в VS Code, используйте команду `MCP: List Servers` и проверьте, что сервер `tavily` доступен.

## Логирование и наблюдаемость

Лог-файл: `calendar_assistant.log`

Новые маркеры:

- `LLM_ROUTE` (provider/model/reason/task_type)
- `LLM_POLICY` (policy decision)
- `LLM_USAGE` (usage/trace, включая latency)

## Smoke-проверки

Провайдер Copilot:

```bash
.venv\Scripts\python.exe scripts\smoke_copilot_provider.py --prompt "Reply with smoke-ok"
```

Gateway routing без сети:

```bash
.venv\Scripts\python.exe scripts\smoke_gateway_flow.py
```

Policy guardrails (positive/negative):

```bash
.venv\Scripts\python.exe scripts\smoke_policy_guardrails.py
```

Research skill smoke:

```bash
.venv\Scripts\python.exe scripts\smoke_research_skill.py --prompt "Исследуй тему retrieval augmented generation"
```

### Python test launcher

Для быстрого запуска тестов без длинных `unittest` команд используйте Python launcher:

```bash
.venv\Scripts\python.exe scripts\run_tests.py fast
.venv\Scripts\python.exe scripts\run_tests.py non-telegram
.venv\Scripts\python.exe scripts\run_tests.py real-copilot
.venv\Scripts\python.exe scripts\run_tests.py all --include-real
```

Что делает:

- `fast` / `non-telegram`: локальные сервисные тесты без Telegram integration и без реального Copilot runtime.
- `real-copilot`: реальные integration tests против `github-copilot-sdk`; скрипт сам выставит `RUN_REAL_COPILOT_INTEGRATION=1`.
- `all --include-real`: объединенный прогон локальных и real Copilot тестов.

Дополнительно:

- `--list` печатает состав suite без запуска.
- `--verbosity 1` или `--verbosity 2` управляет детализацией вывода.

## Research Mode

Поддерживается отдельный intent `research` с использованием skills Copilot runtime (например, `research-pipeline`).

Пользовательский сценарий в Telegram:

- Новый запрос: `Исследуй тему ...`
- Follow-up: `подробнее`, `раскрой пункт 2`, `уточни выводы`
- Команды:
- `/research_help` - примеры и формат
- `/research_sources` - источники из текущего research-контекста
- `/research_reset` - сброс active research-контекста чата

Поведение:

- первый ответ возвращается в компактном формате,
- факты помечаются `[CONFIRMED]`, `[UNCERTAIN]`, `[NOT_FOUND]`,
- источники (URL) сохраняются в локальный кэш,
- follow-up запросы используют сохраненный контекст и дозапрашивают только недостающие данные.

Локальный кэш research:

- по умолчанию: `%TEMP%/selfhosted_assistant/research/<chat_id>/session-*/`
- артефакты: `meta.json`, `brief.md`, `findings.json`, `sources.json`, `turns/*`
- автоматически применяется TTL cleanup и ограничение числа сессий на чат.

Troubleshooting:

- Если research не запускается: проверьте `gh auth login -h github.com -w` и `gh auth status -h github.com`.
- Если skill не подхватывается: проверьте `COPILOT_SKILL_DIRS` и наличие `SKILL.md` в директории.
- Если MCP/tools недоступны: проверьте `TAVILY_API_KEY`, наличие `npx`, файл `.vscode/mcp.json` и статус сервера через `MCP: List Servers`.
- Если ошибка записи кэша: бот продолжит отвечать, но без устойчивого follow-up контекста.

## Rollout / rollback

Rollout:

1. Прогнать smoke-скрипты.
2. Прогнать ручные сценарии для `calendar_event`, `task`, `note`, `unknown`.
3. Проверить логи `LLM_ROUTE/LLM_POLICY/LLM_USAGE`.
4. Включить ограниченный prod-трафик.
5. После стабилизации перевести весь трафик.

Rollback:

1. Проверить `gh auth status -h github.com` и переменные `COPILOT_*`.
2. Перезапустить сервис.
3. Проверить `LLM_ROUTE` и успешность контрольных сценариев.

## Структура проекта (актуальные LLM модули)

```text
selfhosted_assistant/
├── llm_core/
│   ├── contracts.py
│   ├── gateway.py
│   ├── router.py
│   └── policy.py
├── integrations/
│   └── copilot_sdk/
│       └── provider.py
├── request_handlers/
├── request_classifier.py
├── llm_routing_config.json
└── requirements.txt
```
