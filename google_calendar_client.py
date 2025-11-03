from typing import Dict, Any, Optional
import os
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from logger import calendar_logger


SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/tasks']


class GoogleCalendarClient:
    def __init__(self, credentials_path: str = "credentials.json"):
        credentials_path_from_env = os.getenv('GOOGLE_CREDENTIALS_PATH')
        self.credentials_path = credentials_path_from_env or credentials_path

        if not os.path.exists(self.credentials_path):
            raise Exception(f"Credentials file not found: {self.credentials_path}")

        services = self._authenticate()
        self.calendar_service = services.get('calendar')
        self.tasks_service = services.get('tasks')

    def _authenticate(self):
        """Authenticate and return dict with 'calendar' and 'tasks' services."""
        token_json = os.getenv('GOOGLE_OAUTH_TOKEN')
        if token_json:
            try:
                token_data = json.loads(token_json)
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
                if creds and creds.expired and creds.refresh_token:
                    print("🔄 Обновляем истекший токен...")
                    creds.refresh(Request())
                    # Обновляем токен в памяти (не сохраняем в файл)
                    print("✅ Токен обновлен в памяти")
                
                if creds and creds.valid:
                    calendar_logger.info("Using Google token from environment")
                    return {
                        'calendar': build('calendar', 'v3', credentials=creds),
                        'tasks': build('tasks', 'v1', credentials=creds)
                    }
            except Exception as e:
                calendar_logger.warning(f"Failed to load token from env: {e}")

        # Fallback to interactive flow
        return self._authenticate_auto()

    def _authenticate_auto(self):
        """Автоматическая OAuth аутентификация"""
        print("🚀 Запускаем автоматическую авторизацию...")
        print("💡 После авторизации скопируйте токен в main.env для будущего использования")
        
        if not os.path.exists(self.credentials_path):
            raise Exception(f"❌ Файл credentials.json не найден: {self.credentials_path}")
        
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                self.credentials_path, SCOPES)

            try:
                print("🌐 Откроется браузер для авторизации...")
                print("📋 Войдите под аккаунтом разработчика (владельца приложения)")
                creds = flow.run_local_server(port=0)
            except Exception as browser_err:
                print("⚠️ Не удалось открыть браузер (серверный режим). Переключаемся на авторизацию по ссылке...")
                print(f"Причина: {browser_err}")
                print("🔗 Режим авторизации по ссылке (console mode)")
                print("📋 Войдите под аккаунтом разработчика (владельца приложения)")
                creds = flow.run_console()

            # Выводим информацию для добавления в переменные окружения
            self._print_token_info(creds)

            print("✅ Авторизация завершена успешно!")
            print("⚠️ ВАЖНО: Скопируйте токен выше в main.env для постоянного использования")
            return {
                'calendar': build('calendar', 'v3', credentials=creds),
                'tasks': build('tasks', 'v1', credentials=creds)
            }

        except Exception as e:
            raise Exception(f"❌ Ошибка автоматической авторизации: {str(e)}")
    
    def _print_token_info(self, creds):
        try:
            token_data = json.loads(creds.to_json())
            token_json = json.dumps(token_data, separators=(',', ':'))
            
            print("\n" + "="*60)
            print("📋 СКОПИРУЙТЕ ЭТОТ ТОКЕН В main.env:")
            print("="*60)
            print(f"GOOGLE_OAUTH_TOKEN={token_json}")
        except Exception as e:
            calendar_logger.warning(f"Unable to serialize credentials for copy/paste: {e}")

    def create_event(self, event_data: Dict[str, Any], calendar_id: str = 'primary') -> Optional[Dict[str, Any]]:
        try:
            calendar_logger.log_calendar_request(event_data)
            event = self.calendar_service.events().insert(calendarId=calendar_id, body=event_data).execute()
            result = {
                'success': True,
                'event_id': event.get('id'),
                'event_link': event.get('htmlLink'),
                'message': f"Событие '{event_data.get('summary')}' создано успешно"
            }
            calendar_logger.log_calendar_response(True, result)
            return result
        except Exception as e:
            result = {
                'success': False,
                'error': str(e),
                'message': f"Ошибка при создании события: {str(e)}"
            }
            calendar_logger.log_calendar_response(False, result)
            calendar_logger.log_error(e, "google_calendar_client.create_event")
            return result

    def create_task(self, task_data: Dict[str, Any], tasklist: str = '@default') -> Optional[Dict[str, Any]]:
        """Create a task. Resolve tasklist id from env or by matching common titles, validate and fallback to '@default'."""
        try:
            calendar_logger.log_calendar_request(task_data)

            tasklist_id = os.getenv('GOOGLE_TASKLIST_ID')

            if not tasklist_id:
                tasklist_id = tasklist or '@default'

            calendar_logger.info(f"Using tasklist id: {tasklist_id}")

            task = self.tasks_service.tasks().insert(tasklist=tasklist_id, body=task_data).execute()
            result = {
                'success': True,
                'task_id': task.get('id'),
                'task': task,
                'message': f"Задача '{task_data.get('title')}' создана успешно"
            }

            calendar_logger.log_calendar_response(True, result)
            return result

        except Exception as e:
            result = {
                'success': False,
                'error': str(e),
                'message': f"Ошибка при создании задачи: {str(e)}"
            }
            calendar_logger.log_calendar_response(False, result)
            calendar_logger.log_error(e, "google_calendar_client.create_task")
            return result
