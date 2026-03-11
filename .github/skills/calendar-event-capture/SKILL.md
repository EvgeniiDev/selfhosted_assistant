---
name: calendar-event-capture
description: "Извлечение календарных событий в формате CalendarEvent JSON без дополнительного текста."
trigger_phrases:
  - "создай событие"
  - "запланируй встречу"
  - "митинг"
  - "meeting"
---

# Calendar Event Capture

Этот skill является источником поведения для capability `calendar_event`.
Host передает исходный пользовательский текст и runtime-контекст с текущим локальным временем.

## Runtime Contract

Host вызывает skill в режиме `new` и передает `Host context JSON`, где может быть:
- `current_local_datetime`

Skill должен вернуть только компактный JSON без пояснений и markdown:

```json
{"type":"calendar_event","data":{"title":"string","description":"string or null","start_time":"YYYY-MM-DDTHH:MM:SS","end_time":"YYYY-MM-DDTHH:MM:SS or null","duration_minutes":"number or null","recurrence":"string or null"}}
```

## Правила

- Все времена интерпретируй в локальном часовом поясе пользователя.
- Если указан `end_time`, верни его и поставь `duration_minutes: null`.
- Если указана только длительность, верни `duration_minutes`, а `end_time: null`.
- Если не указано ни окончание, ни длительность, ставь `duration_minutes: 60`.
- `recurrence` возвращай только если повторяемость прямо следует из запроса.
- Для даты без года используй текущий год; если дата уже прошла, используй ближайшее следующее вхождение.
- Не добавляй вымышленных деталей.

## Output Rules

- Верни только JSON.
- Никакого дополнительного текста.
- Никаких кодовых блоков.