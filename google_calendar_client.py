from typing import Dict, Any, Optional
import os
import json
import base64
import sys
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

        self.oauth_token_v2_from_env = os.getenv('GOOGLE_OAUTH_TOKEN_V2')
        self.oauth_token_from_env = os.getenv('GOOGLE_OAUTH_TOKEN')
        self.oauth_client_config_from_env = os.getenv('GOOGLE_OAUTH_CLIENT_CONFIG')

        # credentials.json требуется только если нет client config в env
        # и нужен интерактивный OAuth (т.е. нет GOOGLE_OAUTH_TOKEN).
        if (
            not self.oauth_token_v2_from_env
            and
            not self.oauth_token_from_env
            and not self.oauth_client_config_from_env
            and not os.path.exists(self.credentials_path)
        ):
            raise Exception(
                "Credentials file not found and no env-based OAuth config provided. "
                "Set GOOGLE_OAUTH_TOKEN_V2 (preferred), GOOGLE_OAUTH_TOKEN, GOOGLE_OAUTH_CLIENT_CONFIG "
                "or provide credentials.json"
            )

        services = self._authenticate()
        self.calendar_service = services.get('calendar')
        self.tasks_service = services.get('tasks')

    def _authenticate(self):
        """Authenticate and return dict with 'calendar' and 'tasks' services."""
        creds = self._load_credentials_from_env()
        if creds:
            needs_refresh = bool(creds.refresh_token) and (
                not creds.valid or creds.expired or not getattr(creds, 'token', None)
            )

            if needs_refresh:
                try:
                    print("🔄 Обновляем OAuth токен из refresh_token...")
                    creds.refresh(Request())
                    print("✅ Токен обновлен в памяти")
                except Exception as refresh_err:
                    calendar_logger.warning(f"Failed to refresh Google token from environment: {refresh_err}")

            if creds.valid:
                calendar_logger.info("Using Google token from environment")
                return {
                    'calendar': build('calendar', 'v3', credentials=creds),
                    'tasks': build('tasks', 'v1', credentials=creds)
                }

            calendar_logger.warning("Google credentials from environment are not valid; fallback to interactive flow")

        # Fallback to interactive flow
        return self._authenticate_auto()

    def _load_credentials_from_env(self) -> Optional[Credentials]:
        token_v2 = self.oauth_token_v2_from_env or os.getenv('GOOGLE_OAUTH_TOKEN_V2')
        if token_v2:
            try:
                return self._credentials_from_token_v2(token_v2)
            except Exception as e:
                raise Exception(f"Невалидный GOOGLE_OAUTH_TOKEN_V2: {e}")

        token_legacy = self.oauth_token_from_env or os.getenv('GOOGLE_OAUTH_TOKEN')
        if token_legacy:
            try:
                token_data = self._parse_json_env_value(token_legacy, 'GOOGLE_OAUTH_TOKEN')
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
                calendar_logger.warning("Using legacy GOOGLE_OAUTH_TOKEN. Prefer GOOGLE_OAUTH_TOKEN_V2")
                return creds
            except Exception as e:
                calendar_logger.warning(f"Failed to load legacy GOOGLE_OAUTH_TOKEN: {e}")

        return None

    def _credentials_from_token_v2(self, token_v2_json: str) -> Credentials:
        data = self._parse_json_env_value(token_v2_json, 'GOOGLE_OAUTH_TOKEN_V2')

        if not isinstance(data, dict):
            raise Exception("ожидается JSON-объект")

        payload = data.get('authorized_user') if isinstance(data.get('authorized_user'), dict) else data

        if payload.get('type') == 'service_account' or 'private_key' in payload:
            raise Exception("service_account не подходит, нужен user OAuth token")

        required = ['client_id', 'client_secret', 'refresh_token']
        missing = [key for key in required if not payload.get(key)]
        if missing:
            raise Exception(f"отсутствуют обязательные поля: {', '.join(missing)}")

        token_uri = payload.get('token_uri') or payload.get('token_url') or 'https://oauth2.googleapis.com/token'
        token_value = payload.get('token') or payload.get('access_token')

        return Credentials(
            token=token_value,
            refresh_token=payload.get('refresh_token'),
            token_uri=token_uri,
            client_id=payload.get('client_id'),
            client_secret=payload.get('client_secret'),
            scopes=SCOPES,
        )

    def _parse_json_env_value(self, raw_value: str, env_name: str) -> Dict[str, Any]:
        value = (raw_value or '').strip()
        if not value:
            raise Exception('пустое значение')

        candidates = [value]

        if value.startswith('base64:'):
            encoded = value[len('base64:'):].strip()
            try:
                decoded = base64.b64decode(encoded).decode('utf-8')
                candidates.insert(0, decoded)
            except Exception:
                pass

        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            unquoted = value[1:-1].strip()
            if unquoted:
                candidates.insert(0, unquoted)

        last_error = None
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
                last_error = Exception('ожидается JSON-объект')
            except Exception as e:
                last_error = e

        raise Exception(f"не удалось распарсить {env_name}: {last_error}")

    def _authenticate_auto(self):
        """Автоматическая OAuth аутентификация"""
        print("🚀 Запускаем автоматическую авторизацию...")
        print("💡 После авторизации скопируйте токен в main.env для будущего использования")

        if not self._is_interactive_session():
            raise Exception(
                "Интерактивная OAuth-авторизация недоступна в non-interactive окружении (например, systemd). "
                "Сгенерируйте токен один раз в интерактивной сессии и задайте GOOGLE_OAUTH_TOKEN_V2 в main.env."
            )
        
        try:
            flow = InstalledAppFlow.from_client_config(
                self._load_oauth_client_config(), SCOPES)

            try:
                print("🌐 Откроется браузер для авторизации...")
                print("📋 Войдите под аккаунтом разработчика (владельца приложения)")
                creds = flow.run_local_server(port=0)
            except Exception as browser_err:
                print("⚠️ Не удалось открыть браузер (серверный режим). Переключаемся на авторизацию по ссылке...")
                print(f"Причина: {browser_err}")
                print("🔗 Режим авторизации по ссылке (console mode)")
                print("📋 Войдите под аккаунтом разработчика (владельца приложения)")

                # Пытаемся использовать out-of-band метод через ввод кода вручную
                try:
                    # Некоторые версии и клиенты требуют явного указания OOB redirect URI
                    try:
                        flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
                    except Exception:
                        pass

                    auth_url, _ = flow.authorization_url(
                        prompt='consent',
                        access_type='offline',
                        include_granted_scopes='true'
                    )

                    print("\nОткройте эту ссылку в любом браузере:")
                    print(auth_url)
                    print("\nПосле подтверждения скопируйте код подтверждения и вставьте сюда.")
                    code = input("Введите код авторизации: ").strip()

                    flow.fetch_token(code=code)
                    creds = flow.credentials
                except Exception as manual_err:
                    raise Exception(f"Не удалось выполнить авторизацию по ссылке: {manual_err}")

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

    def _is_interactive_session(self) -> bool:
        try:
            return bool(sys.stdin and sys.stdin.isatty())
        except Exception:
            return False

    def _load_oauth_client_config(self) -> Dict[str, Any]:
        """Загружает OAuth client config в формате, подходящем для InstalledAppFlow.

        Поддерживаемые варианты исходного JSON:
        1) {'installed': {...}}
        2) {'web': {...}}
        3) Плоский OAuth формат с ключами client_id/client_secret/auth_uri/token_uri
        """
        raw = None

        env_client_config = self.oauth_client_config_from_env or os.getenv('GOOGLE_OAUTH_CLIENT_CONFIG')
        if env_client_config:
            try:
                raw = self._parse_json_env_value(env_client_config, 'GOOGLE_OAUTH_CLIENT_CONFIG')
            except Exception as e:
                raise Exception(f"Не удалось прочитать GOOGLE_OAUTH_CLIENT_CONFIG: {e}")

        if raw is None:
            if not os.path.exists(self.credentials_path):
                raise Exception(
                    "❌ Файл credentials.json не найден, и GOOGLE_OAUTH_CLIENT_CONFIG не задан"
                )

            try:
                with open(self.credentials_path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
            except Exception as e:
                raise Exception(f"Не удалось прочитать credentials: {e}")
        if not isinstance(raw, dict):
            raise Exception("Неверный формат credentials.json: ожидается JSON-объект")

        if 'installed' in raw or 'web' in raw:
            return raw

        if raw.get('type') == 'service_account' or 'private_key' in raw:
            raise Exception(
                "Обнаружен service account JSON. Для OAuth пользователя нужен OAuth Client ID "
                "типа Desktop app (installed) или Web application (web)."
            )

        required_flat = {'client_id', 'client_secret', 'auth_uri', 'token_uri'}
        if required_flat.issubset(raw.keys()):
            redirect_uris = raw.get('redirect_uris')
            if not isinstance(redirect_uris, list) or not redirect_uris:
                redirect_uris = ['http://localhost']

            return {
                'installed': {
                    'client_id': raw.get('client_id'),
                    'project_id': raw.get('project_id', ''),
                    'auth_uri': raw.get('auth_uri'),
                    'token_uri': raw.get('token_uri'),
                    'auth_provider_x509_cert_url': raw.get(
                        'auth_provider_x509_cert_url',
                        'https://www.googleapis.com/oauth2/v1/certs'
                    ),
                    'client_secret': raw.get('client_secret'),
                    'redirect_uris': redirect_uris,
                }
            }

        raise Exception(
            "Неподдерживаемый формат credentials.json. Ожидается ключ 'installed' или 'web', "
            "либо плоский OAuth JSON с client_id/client_secret/auth_uri/token_uri."
        )
    
    def _print_token_info(self, creds):
        try:
            token_data = json.loads(creds.to_json())
            token_json = json.dumps(token_data, separators=(',', ':'))

            token_v2_payload = {
                "client_id": token_data.get("client_id"),
                "client_secret": token_data.get("client_secret"),
                "refresh_token": token_data.get("refresh_token"),
                "token_uri": token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            }
            token_v2_json = json.dumps(token_v2_payload, separators=(',', ':'))
            
            print("\n" + "="*60)
            print("📋 СКОПИРУЙТЕ ЭТОТ ТОКЕН В main.env (предпочтительно V2):")
            print("="*60)
            print(f"GOOGLE_OAUTH_TOKEN_V2={token_v2_json}")
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
