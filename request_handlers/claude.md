# Request Handlers Index

Каталог содержит специализированные обработчики intent-ов после классификации запроса.

## Файлы
- `base_handler.py` - общий интерфейс и базовая логика обработчиков.
- `classification_handler.py` - слой, связанный с классификацией входящего сообщения.
- `calendar_event_handler.py` - извлечение и обработка календарных событий.
- `task_handler.py` - создание и разбор задач.
- `note_handler.py` - создание и сохранение заметок.
- `__init__.py` - пакетный маркер.

## Как читать каталог
- Сначала `base_handler.py`, чтобы понять общий контракт.
- Затем нужный intent-specific handler.
- Для маршрутизации между intent-ами смотри `request_classifier.py` и `chat_application_service.py`.