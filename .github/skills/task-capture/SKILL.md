---
name: task-capture
description: "Извлечение задач и напоминаний в формате Task JSON без дополнительного текста."
trigger_phrases:
  - "создай задачу"
  - "напомни"
  - "todo"
  - "task"
---

# Task Capture

Этот skill является источником поведения для capability `task`.
Host передает исходный пользовательский текст и runtime-контекст с текущим локальным временем.

## Runtime Contract

Host вызывает skill в режиме `new` и передает `Host context JSON`, где может быть:
- `current_local_datetime`

Skill должен вернуть только компактный JSON без пояснений и markdown:

```json
{"type":"task","data":{"title":"string","description":"string or null","due_time":"YYYY-MM-DDTHH:MM:SS or null","duration_minutes":"number or null","recurrence":"string or null"}}
```

## Правила

- Пользователь хочет создать задачу или напоминание.
- `due_time` указывай только если он действительно извлекается из запроса.
- Если время не указано, верни `due_time: null`.
- Если длительность указана, верни число минут в `duration_minutes`.
- Не добавляй вымышленных деталей.
- `recurrence` возвращай только если повторяемость прямо следует из запроса.

## Output Rules

- Верни только JSON.
- Никакого дополнительного текста.
- Никаких кодовых блоков.