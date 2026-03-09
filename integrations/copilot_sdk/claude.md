# Copilot SDK Provider Index

Основной production-провайдер LLM в этом репозитории.

## Файлы
- `provider.py` - обертка над GitHub Copilot SDK: auth check, persistent async loop, session reuse, timeout/retry logic, skill directories и MCP server wiring.
- `__init__.py` - пакетный маркер.

## Что важно понимать
- Провайдер работает через долгоживущую async loop, а не через `asyncio.run(...)` на каждый запрос.
- Research сценарии зависят от устойчивых Copilot sessions и корректного session id.
- Конфигурация берется из env и `llm_routing_config.json`, а MCP может подключаться через `mcp_servers`.

## С какими файлами читать вместе
- `llm_core/contracts.py` - формат `LLMRequest` и `LLMResponse`.
- `llm_core/gateway.py` - место вызова provider.
- `research_service.py` - как research flow формирует запрос в provider.
- `tests/test_copilot_provider_sessions.py` - локальные сценарии session management.
- `tests/test_real_copilot_research_integration.py` - реальная интеграция с runtime.