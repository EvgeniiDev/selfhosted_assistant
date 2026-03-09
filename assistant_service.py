from typing import Dict, Any
from datetime import datetime

from request_classifier import RequestClassifier
from google_calendar_client import GoogleCalendarClient
from google_drive_client import GoogleDriveClient
from google_oauth_client import GoogleOAuthClient
from models import CalendarEvent, Note, Task, ResearchRequest, ListNotesRequest
from logger import calendar_logger


class AssistantService:
    def __init__(self):
        self.inference = RequestClassifier()
        self.calendar_client = None
        self.google_init_error = None
        self.notes_client = None
        self.notes_init_error = None
        self.oauth_client = GoogleOAuthClient(scopes=GoogleOAuthClient.DEFAULT_SCOPES)

        try:
            self.calendar_client = GoogleCalendarClient(oauth_client=self.oauth_client)
        except Exception as e:
            self.google_init_error = str(e)
            calendar_logger.log_error(e, "assistant_service.__init__ - GoogleCalendarClient")

        try:
            self.notes_client = GoogleDriveClient(oauth_client=self.oauth_client)
        except Exception as e:
            self.notes_init_error = str(e)
            calendar_logger.warning(f"GoogleDriveClient unavailable: {e}")

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
                    save_result = self._save_note_to_keep(result)
                    return {
                        'success': True,
                        'action': 'note',
                        'note': result,
                        'message': self._format_note_response(result, save_result=save_result)
                    }
                
                case ListNotesRequest():
                    return self._list_keep_notes()
                
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

    def _format_note_response(self, note: Note, save_result: Dict[str, Any] | None = None) -> str:
        """Форматирует ответ по заметке без дублирования полного текста."""
        resolved_title = (save_result or {}).get('title', note.title)
        summary = (note.content or '').strip()
        preview = summary if len(summary) <= 220 else summary[:217].rstrip() + '...'

        lines = [
            "📝 **Заметка готова**",
            "",
            f"**Тема:** {resolved_title}",
        ]

        if preview:
            lines.extend(["", f"**Кратко:** {preview}"])

        # Дата создания берется из метаданных файла (Drive createdTime), если доступна.
        created_at = (save_result or {}).get('created_at')
        if created_at:
            try:
                created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                lines.extend(["", f"📅 Создано: {created_time.strftime('%d.%m.%Y в %H:%M')}"])
            except Exception:
                pass

        web_link = (save_result or {}).get('web_link')
        if web_link:
            lines.extend(["", f"[Открыть заметку]({web_link})"])

        if (save_result or {}).get('success'):
            lines.extend(["", "✅ Сохранено"])

        return "\n".join(lines)

    def _save_note_to_keep(self, note: Note) -> Dict[str, Any]:
        """Сохраняет заметку в хранилище и возвращает метаданные файла."""
        if not self.notes_client:
            return {'success': False}

        title = (note.title or "").strip()
        body_text = (note.content or "").strip()

        return self.notes_client.save_note(title, body_text) or {'success': False}

    def _list_keep_notes(self) -> Dict[str, Any]:
        """Получает список заметок из хранилища."""
        if not self.notes_client:
            return {
                'success': False,
                'message': f'Сервис заметок недоступен: {self.notes_init_error or "проверьте настройки авторизации"}',
            }

        result = self.notes_client.list_notes(page_size=10) or {}
        if not result.get('success'):
            return {
                'success': False,
                'message': result.get('message') or 'Ошибка при получении заметок',
            }

        files = result.get('files', [])
        return {
            'success': True,
            'action': 'list_notes',
            'files': files,
            'message': self._format_drive_notes_list(files),
        }

    def _format_drive_notes_list(self, files: list) -> str:
        """Форматирует список заметок."""
        if not files:
            return "📝 Заметок не найдено."
        lines = [f"📝 **Список заметок** ({len(files)}):\n"]
        for i, file in enumerate(files, 1):
            title = file.get('name', '*(без названия)*')
            if title.lower().endswith('.txt'):
                title = title[:-4]

            created_time = file.get('createdTime', '')
            created_label = ''
            if created_time:
                try:
                    parsed = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                    created_label = parsed.strftime('%d.%m.%Y %H:%M')
                except Exception:
                    created_label = created_time

            web_link = file.get('webViewLink', '')
            lines.append(f"**{i}. {title}**")
            if created_label:
                lines.append(f"📅 {created_label}")
            if web_link:
                lines.append(f"[Открыть]({web_link})")
            lines.append("")
        return "\n".join(lines).rstrip()

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
