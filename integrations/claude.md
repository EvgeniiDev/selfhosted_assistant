# Integrations Index

Здесь лежат адаптеры к внешним LLM/runtime системам.

## Поддиректории
- `copilot_sdk/claude.md` - основной рабочий адаптер GitHub Copilot SDK.
- `openrouter/claude.md` - заготовка под альтернативный provider.

## Роль каталога
- Изолирует внешний runtime от core-контрактов в `llm_core/`.
- Дает place для provider-specific кода, auth, session lifecycle и MCP integration.