from typing import Dict, Any
from datetime import datetime

from request_classifier import RequestClassifier
from google_calendar_client import GoogleCalendarClient
from models import CalendarEvent, Note, Task, ResearchRequest
from logger import calendar_logger


class AssistantService:
    def __init__(self):
        self.inference = RequestClassifier()
        self.calendar_client = None
        self.google_init_error = None

        try:
            self.calendar_client = GoogleCalendarClient()
        except Exception as e:
            self.google_init_error = str(e)
            calendar_logger.log_error(e, "assistant_service.__init__ - GoogleCalendarClient")

    def process_user_request(self, user_message: str) -> Dict[str, Any]:
        """Обрабатывает запрос пользователя и создает событие в календаре или возвращает заметку"""
        try:
            # Получаем CalendarEvent или Note от модели
            result = self.inference.process_request(user_message)

            if not result:
                return {
                    'success': False,
                    'message': 'Не удалось понять запрос. Попробуйте переформулировать.'
                }

            # Обрабатываем результат в зависимости от типа
            match result:
                case Note():
                    # Заметка - возвращаем её сразу
                    return {
                        'success': True,
                        'action': 'note',
                        'note': result,
                        'message': self._format_note_response(result)
                    }
                
                case CalendarEvent():
                    # Календарное событие - возвращаем данные для подтверждения
                    return {
                        'success': True,
                        'action': 'confirm',
                        'event': result,
                        'message': self._format_event_confirmation(result)
                    }
                case Task():
                    # Для задач используем отдельный подтверждающий поток
                    return {
                        'success': True,
                        'action': 'confirm_task',
                        'task': result,
                        'message': self._format_task_confirmation(result)
                    }
                case ResearchRequest():
                    mode = self._detect_research_mode(result.original_query)
                    return {
                        'success': True,
                        'action': 'research',
                        'original_query': result.original_query,
                        'mode': mode,
                    }
                
                case _:
                    # Неожиданный тип объекта
                    return {
                        'success': False,
                        'message': 'Получен неожиданный тип объекта. Попробуйте переформулировать запрос.'
                    }

        except Exception as e:
            calendar_logger.log_error(e, "assistant_service.process_user_request")
            return {
                'success': False,
                'message': f'Произошла ошибка: {str(e)}'
            }

    def create_confirmed_event(self, calendar_event: CalendarEvent) -> Dict[str, Any]:
        """Создает подтвержденное событие в Google Calendar"""
        try:
            if not self.calendar_client:
                return {
                    'success': False,
                    'message': f'Google Calendar не настроен: {self.google_init_error or "проверьте GOOGLE_OAUTH_TOKEN_V2 (или credentials.json для первичной авторизации)"}'
                }

            # Создаем событие в Google Calendar
            google_event_data = calendar_event.to_google_event()
            result = self.calendar_client.create_event(google_event_data)

            return result or {
                'success': False,
                'message': 'Неожиданная ошибка при создании события'
            }

        except Exception as e:
            calendar_logger.log_error(e, "assistant_service.create_confirmed_event")
            return {
                'success': False,
                'message': f'Произошла ошибка при создании события: {str(e)}'
            }

    def _format_event_confirmation(self, event: CalendarEvent) -> str:
        """Форматирует событие для подтверждения пользователем"""
        # Форматируем время начала
        start_time_str = event.start_time.strftime("%d.%m.%Y в %H:%M")
        
        # Форматируем время окончания
        if event.end_time:
            end_time_str = event.end_time.strftime("%H:%M")
            duration_str = f"до {end_time_str}"
        elif event.duration_minutes:
            hours = event.duration_minutes // 60
            minutes = event.duration_minutes % 60
            if hours > 0 and minutes > 0:
                duration_str = f"({hours}ч {minutes}мин)"
            elif hours > 0:
                duration_str = f"({hours}ч)"
            else:
                duration_str = f"({minutes}мин)"
        else:
            duration_str = "(1ч)"

        # Форматируем повторяемость
        recurrence_str = ""
        if event.recurrence:
            recurrence_str = "\n🔄 Повторяемость: Да"

        # Собираем сообщение
        message = f"""📅 **Подтверждение события**

📝 **Название:** {event.title}
⏰ **Время:** {start_time_str} {duration_str}"""

        if event.description:
            message += f"\n📋 **Описание:** {event.description}"
        
        message += recurrence_str
        message += "\n\n✅ Подтвердить создание события?"

        return message

    def _format_note_response(self, note: Note) -> str:
        """Форматирует заметку для отправки пользователю"""
        # Форматируем дату создания
        try:
            created_time = datetime.fromisoformat(note.created_at)
            created_str = created_time.strftime("%d.%m.%Y в %H:%M")
        except:
            created_str = note.created_at

        # Собираем сообщение
        message = f"""📝 **Ваша заметка**

**{note.title}**

{note.content}

📅 Создано: {created_str}"""

        # Добавляем теги, если они есть
        if note.tags and len(note.tags) > 0:
            tags_str = " ".join([f"#{tag}" for tag in note.tags])
            message += f"\n🏷️ Теги: {tags_str}"

        return message

    def _task_to_calendar_event(self, task: Task) -> CalendarEvent:
        """Convert Task to CalendarEvent for confirmation/creation."""
        # If task has due_time, use it as start_time
        start_time = task.due_time if task.due_time else datetime.now()
        # Map duration -> duration_minutes
        duration = task.duration_minutes if task.duration_minutes else None

        event = CalendarEvent(
            title=task.title,
            description=task.description,
            start_time=start_time,
            duration_minutes=duration,
            recurrence=task.recurrence,
            timezone=task.timezone
        )

        return event

    def create_confirmed_task(self, task: Task) -> Dict[str, Any]:
        """Создает подтвержденную задачу через Google Tasks API"""
        try:
            if not self.calendar_client:
                return {
                    'success': False,
                    'message': f'Google Tasks не настроен: {self.google_init_error or "проверьте GOOGLE_OAUTH_TOKEN_V2 (или credentials.json для первичной авторизации)"}'
                }

            task_payload = task.to_google_task()
            result = self.calendar_client.create_task(task_payload)
            return result or {
                'success': False,
                'message': 'Неожиданная ошибка при создании задачи'
            }

        except Exception as e:
            calendar_logger.log_error(e, "assistant_service.create_confirmed_task")
            return {
                'success': False,
                'message': f'Произошла ошибка при создании задачи: {str(e)}'
            }

    def _format_task_confirmation(self, task: Task) -> str:
        """Форматирует задачу для подтверждения пользователем"""
        due_str = task.due_time.strftime("%d.%m.%Y в %H:%M") if task.due_time else "без точного времени"
        msg = f"📝 **Задача:** {task.title}\n⏰ **Срок:** {due_str}"
        if task.description:
            msg += f"\n📋 {task.description}"
        msg += "\n\n✅ Создать задачу?"
        return msg

    def _detect_research_mode(self, user_message: str) -> str:
        text = (user_message or "").lower()
        followup_hints = (
            "подробнее",
            "раскрой",
            "уточни",
            "детальнее",
            "детальней",
            "пункт",
            "follow-up",
            "follow up",
            "more details",
            "elaborate",
        )
        return "followup" if any(hint in text for hint in followup_hints) else "new"
