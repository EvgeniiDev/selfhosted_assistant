# Research Mode Plan (Skill-First + Context Cache)

## 1. Objective

Goal: implement `research mode` in Telegram bot using ready Copilot Skill(s), with local aggregated context for follow-up answers.

What already exists:
- Skill exists: `.github/skills/research-pipeline/SKILL.md`
- LLM provider exists: `integrations/copilot_sdk/provider.py`
- Telegram routing exists: `telegram_bot.py -> assistant_service.py -> request_classifier.py`
- LLM routing/policy exists: `llm_routing_config.json`, `llm_core/*`

Core decision:
- Do not build a custom heavy `research/` orchestrator subsystem in V1.
- Reuse Copilot runtime capabilities (skills, built-in tool orchestration, MCP).
- Add a lightweight local context cache per Telegram chat for stable follow-ups.

## 2. Why this approach

Benefits versus fully custom research engine:
- Small code surface, lower maintenance risk.
- No duplicate orchestration logic already encoded in the skill and runtime.
- Faster rollout without breaking current calendar/task/note flows.
- Follow-up quality improves via local saved context.

Trade-offs:
- Runtime behavior (tooling/session internals) is partially non-deterministic.
- Deep control over search strategy remains inside Copilot runtime.
- Requires Copilot CLI auth/runtime availability.

## 3. Scope and constraints

### 3.1 Sources to cover

Target in V1:
- Web pages/sites
- GitHub repositories/source code
- MCP-backed sources that are whitelisted in config

Telegram channels in V1:
- Best effort only (public web mirrors/pages if available)
- Native Telegram channel ingestion requires dedicated API/MCP integration (V2+)

### 3.2 Response behavior

Mandatory UX contract:
1. First answer is short/compact.
2. Follow-up questions ("подробнее", "раскрой пункт N") are answered from saved aggregated context.
3. If context is insufficient, system performs incremental research and updates context.

## 4. Target architecture in this repo

### 4.1 High-level flow

1. User sends Telegram message.
2. Classifier marks request as `research` (new intent).
3. Assistant returns `action: research` plus mode (`new` or `followup`).
4. Telegram layer builds research prompt wrapper and sends through existing LLM path.
5. Copilot runtime loads `.github/skills/research-pipeline` and runs research workflow.
6. Bot saves structured summary/facts/sources to local context cache.
7. Bot returns compact answer (+ sources). Follow-ups reuse cached context.

### 4.2 Integration boundaries

Keep existing layers:
- `request_classifier.py`: add `research` classification.
- `assistant_service.py`: add `research` action branch.
- `telegram_bot.py`: add research route, long-message split, UX commands.
- `integrations/copilot_sdk/provider.py`: pass skill directories and skill toggles.

Add lightweight new module:
- `research_context_store.py`: file-based context persistence only.

Do not add in V1:
- No custom search crawler framework.
- No bespoke multi-agent orchestrator implementation.
- No persistent DB for research sessions.

## 5. Local context cache design

### 5.1 Storage location

Default:
- `%TEMP%/selfhosted_assistant/research/`

Config:
- `RESEARCH_CONTEXT_DIR` overrides default path.

### 5.2 File structure

```text
<RESEARCH_CONTEXT_DIR>/
  <chat_id>/
    session-<timestamp>/
      meta.json
      brief.md
      findings.json
      sources.json
      turns/
        001_user.txt
        001_assistant.md
        002_user.txt
```

### 5.3 Minimal schema

`meta.json`:
- `chat_id`
- `session_id`
- `created_at`
- `last_updated_at`
- `status` (`active|closed|failed`)

`findings.json`:
- list of `{ claim, status, source_ids }`
- `status` in `CONFIRMED|UNCERTAIN|NOT_FOUND`

`sources.json`:
- list of `{ id, url, title, source_type, fetched_at }`

### 5.4 Lifecycle

- TTL cleanup (default 24h)
- max retained sessions per chat (for example 3)
- `/research_reset` removes active chat session

## 6. Required code changes

### 6.1 Copilot SDK provider

File: `integrations/copilot_sdk/provider.py`

Add in `SessionConfig`:
- `working_directory` (project root)
- `skill_directories` (default `.github/skills`)
- optional `disabled_skills`

Env vars:
- `COPILOT_SKILL_DIRS` (semicolon-separated; default `.github/skills`)
- `COPILOT_DISABLED_SKILLS` (comma-separated)
- `COPILOT_RESEARCH_AGENT` (optional, future)

Keep unchanged:
- current timeout/retry/auth behavior

### 6.2 Request classification

File: `request_handlers/classification_handler.py`

Update:
- add `research` to valid types
- extend prompt category list
- add RU/EN heuristic keywords:
  - `исследуй`, `найди информацию`, `проведи исследование`, `deep dive`, `investigate`, `research`

### 6.3 Request classifier

File: `request_classifier.py`

Update:
- allow `classification == "research"`
- return lightweight research payload object (not `Note/Task/Event`)

### 6.4 Assistant service

File: `assistant_service.py`

Add action branch:
- `research` -> return:
  - `success: true`
  - `action: "research"`
  - `original_query`
  - `mode: "new" | "followup"`

Important:
- do not break existing contracts for calendar/task/note/unknown

### 6.5 Telegram bot

File: `telegram_bot.py`

Add routing branch for `action == "research"`:
- detect per-chat mode: new/followup
- build prompt wrapper for skill usage
- call LLM through existing service/provider flow
- save response and extracted artifacts in context store
- send compact answer, then optional details on demand

Add helpers:
- `_send_long_message(chat_id, text, parse_mode=None)` split at ~3900 chars
- `_is_research_followup(text)` heuristic
- context-aware prompt builder

Add commands:
- `/research_help` usage examples
- `/research_reset` clear active context
- `/research_sources` show saved source URLs

### 6.6 Routing config

File: `llm_routing_config.json`

Minimal change:
- add `research` into `task_types` for active/standby models

Keep unchanged:
- `policies.text_only`
- `allow_mcp_tools`
- `allowed_mcp_servers`

### 6.7 Documentation

File: `README.md`

Add section:
- enabling skill directories (`COPILOT_SKILL_DIRS`)
- research mode usage and follow-up behavior
- context cache directory and cleanup
- troubleshooting when skill or auth is unavailable

## 7. Prompt contracts

### 7.1 New research request

```text
Используй skill `research-pipeline` из подключенных skills.
Тема: <user_text>

Требования к ответу:
1) Краткий итог (3-7 пунктов)
2) Факты с метками [CONFIRMED]/[UNCERTAIN]/[NOT_FOUND]
3) Список источников (URL)
4) Что осталось непроверенным
```

### 7.2 Follow-up request

```text
Используй skill `research-pipeline`.
Это follow-up к предыдущему исследованию.

Вопрос пользователя: <followup_text>
Контекст предыдущего исследования:
- Краткий итог: <brief>
- Ключевые факты: <top findings>
- Источники: <top sources>

Требования:
1) Ответь по существующему контексту
2) Если данных мало, добери только недостающее
3) Отметь новые данные и новые источники отдельно
```

## 8. Rollout plan

### Iteration 1 (MVP)

1. Enable `skill_directories` in Copilot SDK provider.
2. Add `research` intent in classification and request flow.
3. Add Telegram research route + long-message splitting.
4. Add file-based context cache module.
5. Update README + add smoke script.

Definition of done:
- `Исследуй тему X` returns structured compact research response.
- Output includes source URLs and confidence markers.
- Follow-up uses prior context (not full restart).
- Existing calendar/task/note flows still pass smoke checks.

### Iteration 2 (stability)

1. Add schema validation for structured research output.
2. Add retry policy for transient tool/runtime failures.
3. Add per-chat rate limiting/cooldown for research requests.
4. Add cleanup job/trigger for expired context sessions.

### Iteration 3 (advanced)

1. Optional custom agent profile for `research` mode.
2. Better Telegram channel integration via dedicated connector/MCP.
3. Add `/research_status` command with session metadata.

## 9. Testing plan

### Smoke

- `scripts/smoke_copilot_provider.py --prompt "Reply with exactly: smoke-ok"`
- new `scripts/smoke_research_skill.py`:
  - send research prompt
  - assert non-empty response
  - assert at least one URL-like pattern

### Integration

1. Telegram message `Исследуй тему ...` goes through `action=research` path.
2. Follow-up `Подробнее про пункт 2` reuses cached context.
3. Output splits correctly when >4096 chars.
4. Non-research messages keep old behavior.
5. Skill unavailable -> graceful fallback text.

### Failure handling

- Copilot auth invalid -> user-facing instruction (`gh auth login`).
- Skill dir missing -> warning + generic structured prompt.
- MCP/tools unavailable -> partial response with uncertainty markers.
- Context write error -> continue without cache, warn in logs.

## 10. Risks and mitigations

Risk: skill not auto-triggered.
- Mitigation: explicit prompt wrapper with skill name and expected format.

Risk: output too long for Telegram.
- Mitigation: `_send_long_message` helper.

Risk: follow-up quality degrades without memory.
- Mitigation: local context cache + mode-aware prompts.

Risk: behavior drift after skill edits.
- Mitigation: regression smoke checks and stable response checklist.

Risk: Telegram channel coverage incomplete.
- Mitigation: document V1 limits; add dedicated connector in V2.

## 11. Sprint-ready tasks

1. Update `integrations/copilot_sdk/provider.py` to pass `skill_directories`.
2. Add env parsing for `COPILOT_SKILL_DIRS` and `COPILOT_DISABLED_SKILLS`.
3. Extend `request_handlers/classification_handler.py` with `research` intent.
4. Extend `request_classifier.py` and `assistant_service.py` for `action="research"`.
5. Add `research_context_store.py` with chat/session file persistence.
6. Route research in `telegram_bot.py` and add long-message helper.
7. Add `/research_help`, `/research_reset`, `/research_sources` commands.
8. Add `research` to `llm_routing_config.json` model task types.
9. Add `scripts/smoke_research_skill.py`.
10. Document setup and usage in `README.md`.

This plan prioritizes ready Skills and adds a minimal local context layer for high-quality follow-up answers without introducing a heavy custom research backend.
