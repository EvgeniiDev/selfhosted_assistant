# Skills Index

Здесь лежат skill-описания, которые может подхватывать GitHub Copilot через `COPILOT_SKILL_DIRS`.

## Поддиректории
- `research-pipeline/claude.md` - исследовательский skill для deep research сценариев.

## Основные правила
- В каждой skill-папке источником истины является `SKILL.md`.
- Trigger phrases и frontmatter должны оставаться синхронными с фактическим поведением skill.
- Если skill не загружается, сначала проверь `SKILL.md`, затем `README.md`, затем `COPILOT_SKILL_DIRS`.