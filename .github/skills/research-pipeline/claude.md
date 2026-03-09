# Research Pipeline Index

Эта папка содержит skill `research-pipeline` для research intent-ов и глубоких исследований.

## Главный файл
- `SKILL.md` - frontmatter, trigger phrases, оркестрация ролей, handoff-форматы и требования к качеству.

## Что делает skill
- Активирует исследовательский пайплайн по фразам вроде `исследуй тему`.
- Описывает роли `research-senior`, `research-editor`, `research-communicator`.
- Требует явной верификации фактов, меток `[CONFIRMED]`, `[UNCERTAIN]`, `[NOT_FOUND]`.
- Предполагает использование Tavily/MCP при доступности инструментов.

## Когда менять
- Нужно поправить триггеры research intent-а.
- Нужно изменить формат handoff или финального документа.
- Нужно усилить требования к проверке источников или остановкам review-gate.

## Связанные runtime-места
- `research_service.py` - запускает research запросы.
- `integrations/copilot_sdk/provider.py` - подключает Copilot session и MCP servers.
- `.vscode/mcp.json` - конфигурация Tavily MCP в workspace.