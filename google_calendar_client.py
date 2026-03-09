from typing import Dict, Any, Optional
import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_base_client import GoogleBaseClient
from google_oauth_client import GoogleOAuthClient
from logger import calendar_logger


class GoogleCalendarClient(GoogleBaseClient):

    SCOPES = [
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/tasks',
    ]

    def __init__(self, credentials_path: str = "credentials.json", oauth_client: Optional[GoogleOAuthClient] = None):
        self.calendar_service = None
        self.tasks_service = None
        super().__init__(credentials_path, oauth_client=oauth_client)

    def _setup_services(self, creds: Credentials) -> None:
        self.calendar_service = build('calendar', 'v3', credentials=creds)
        self.tasks_service = build('tasks', 'v1', credentials=creds)

    # ------------------------------------------------------------------
    # Calendar API
    # ------------------------------------------------------------------

    def create_event(self, event_data: Dict[str, Any], calendar_id: str = 'primary') -> Optional[Dict[str, Any]]:
        try:
            calendar_logger.log_calendar_request(event_data)
            event = self.calendar_service.events().insert(calendarId=calendar_id, body=event_data).execute()
            result = {
                'success': True,
                'event_id': event.get('id'),
                'event_link': event.get('htmlLink'),
                'message': f"Событие '{event_data.get('summary')}' создано успешно",
            }
            calendar_logger.log_calendar_response(True, result)
            return result
        except Exception as e:
            result = {
                'success': False,
                'error': str(e),
                'message': f"Ошибка при создании события: {e}",
            }
            calendar_logger.log_calendar_response(False, result)
            calendar_logger.log_error(e, "google_calendar_client.create_event")
            return result

    # ------------------------------------------------------------------
    # Tasks API
    # ------------------------------------------------------------------

    def create_task(self, task_data: Dict[str, Any], tasklist: str = '@default') -> Optional[Dict[str, Any]]:
        """Create a task. Resolves tasklist id from env or falls back to '@default'."""
        try:
            calendar_logger.log_calendar_request(task_data)

            tasklist_id = os.getenv('GOOGLE_TASKLIST_ID') or tasklist or '@default'
            calendar_logger.info(f"Using tasklist id: {tasklist_id}")

            task = self.tasks_service.tasks().insert(tasklist=tasklist_id, body=task_data).execute()
            result = {
                'success': True,
                'task_id': task.get('id'),
                'task': task,
                'message': f"Задача '{task_data.get('title')}' создана успешно",
            }
            calendar_logger.log_calendar_response(True, result)
            return result

        except Exception as e:
            result = {
                'success': False,
                'error': str(e),
                'message': f"Ошибка при создании задачи: {e}",
            }
            calendar_logger.log_calendar_response(False, result)
            calendar_logger.log_error(e, "google_calendar_client.create_task")
            return result
