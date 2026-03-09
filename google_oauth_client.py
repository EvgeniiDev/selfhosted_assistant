"""Shared Google OAuth2 authentication client for Calendar, Tasks, and Drive."""
from typing import Dict, Any, Optional, List
import os
import json
import base64
import sys
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from logger import calendar_logger


class GoogleOAuthClient:
    """Provides shared OAuth2 auth flow for Google APIs."""

    _SHARED_CREDS: Optional[Credentials] = None

    DEFAULT_SCOPES: List[str] = [
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/tasks',
        'https://www.googleapis.com/auth/drive.file',
    ]

    def __init__(self, scopes: Optional[List[str]] = None, credentials_path: str = "credentials.json"):
        credentials_path_from_env = os.getenv('GOOGLE_CREDENTIALS_PATH')
        self.credentials_path = credentials_path_from_env or credentials_path

        self.scopes = scopes or self.DEFAULT_SCOPES

        self.oauth_token_v2_from_env = os.getenv('GOOGLE_OAUTH_TOKEN_V2')
        self.oauth_token_from_env = os.getenv('GOOGLE_OAUTH_TOKEN')
        self.oauth_client_config_from_env = os.getenv('GOOGLE_OAUTH_CLIENT_CONFIG')

    def authenticate(self) -> Credentials:
        shared_creds = GoogleOAuthClient._SHARED_CREDS
        if shared_creds and self._can_use_credentials(shared_creds):
            return shared_creds

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
                    calendar_logger.warning(f"Failed to refresh Google token: {refresh_err}")

            if creds.valid:
                calendar_logger.info("GoogleOAuthClient: using token from environment")
                GoogleOAuthClient._SHARED_CREDS = creds
                return creds

            calendar_logger.warning(
                "GoogleOAuthClient: credentials not valid; fallback to interactive flow"
            )

        creds = self._authenticate_auto()
        GoogleOAuthClient._SHARED_CREDS = creds
        return creds

    def _can_use_credentials(self, creds: Credentials) -> bool:
        if not creds or not isinstance(creds, Credentials):
            return False

        if not self._has_required_scopes(creds):
            return False

        needs_refresh = bool(getattr(creds, 'refresh_token', None)) and (
            not getattr(creds, 'valid', False)
            or getattr(creds, 'expired', False)
            or not getattr(creds, 'token', None)
        )
        if needs_refresh:
            try:
                creds.refresh(Request())
            except Exception as refresh_err:
                calendar_logger.warning(f"Failed to refresh cached Google token: {refresh_err}")

        return bool(getattr(creds, 'valid', False))

    def _has_required_scopes(self, creds: Credentials) -> bool:
        try:
            return creds.has_scopes(self.scopes)
        except Exception:
            return True

    def _authenticate_auto(self) -> Credentials:
        """Interactive OAuth flow."""
        print("🚀 Запускаем автоматическую авторизацию...")
        print("💡 После авторизации скопируйте токен в main.env для будущего использования")

        if not self._is_interactive_session():
            raise Exception(
                "Интерактивная OAuth-авторизация недоступна в non-interactive окружении (например, systemd). "
                "Сгенерируйте токен один раз в интерактивной сессии и задайте GOOGLE_OAUTH_TOKEN_V2 в main.env."
            )

        try:
            flow = InstalledAppFlow.from_client_config(
                self._load_oauth_client_config(), self.scopes
            )

            try:
                print("🌐 Откроется браузер для авторизации...")
                print("📋 Войдите под аккаунтом разработчика (владельца приложения)")
                creds = flow.run_local_server(port=0)
            except Exception as browser_err:
                print("⚠️ Не удалось открыть браузер. Переключаемся на авторизацию по ссылке...")
                print(f"Причина: {browser_err}")
                try:
                    try:
                        flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
                    except Exception:
                        pass

                    auth_url, _ = flow.authorization_url(
                        prompt='consent',
                        access_type='offline',
                        include_granted_scopes='true',
                    )
                    print("\nОткройте эту ссылку в любом браузере:")
                    print(auth_url)
                    print("\nПосле подтверждения скопируйте код подтверждения и вставьте сюда.")
                    code = input("Введите код авторизации: ").strip()
                    flow.fetch_token(code=code)
                    creds = flow.credentials
                except Exception as manual_err:
                    raise Exception(f"Не удалось выполнить авторизацию по ссылке: {manual_err}")

            self._print_token_info(creds)
            print("✅ Авторизация завершена успешно!")
            print("⚠️ ВАЖНО: Скопируйте токен выше в main.env для постоянного использования")
            return creds

        except Exception as e:
            raise Exception(f"❌ Ошибка автоматической авторизации: {e}")

    def _load_credentials_from_env(self) -> Optional[Credentials]:
        token_v2 = self.oauth_token_v2_from_env or os.getenv('GOOGLE_OAUTH_TOKEN_V2')
        if token_v2:
            try:
                return self._credentials_from_token_v2(token_v2)
            except Exception as e:
                calendar_logger.warning(f"GoogleOAuthClient: невалидный GOOGLE_OAUTH_TOKEN_V2: {e}. Переходим к интерактивной авторизации.")
                print(f"⚠️  Невалидный GOOGLE_OAUTH_TOKEN_V2: {e}")
                print("🔄 Запускаем интерактивную авторизацию...")

        token_legacy = self.oauth_token_from_env or os.getenv('GOOGLE_OAUTH_TOKEN')
        if token_legacy:
            try:
                token_data = self._parse_json_env_value(token_legacy, 'GOOGLE_OAUTH_TOKEN')
                creds = Credentials.from_authorized_user_info(token_data, self.scopes)
                calendar_logger.warning(
                    "GoogleOAuthClient: using legacy GOOGLE_OAUTH_TOKEN. Prefer GOOGLE_OAUTH_TOKEN_V2"
                )
                return creds
            except Exception as e:
                calendar_logger.warning(f"GoogleOAuthClient: failed to load GOOGLE_OAUTH_TOKEN: {e}")

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
            scopes=self.scopes,
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

    def _load_oauth_client_config(self) -> Dict[str, Any]:
        """Load OAuth client config for InstalledAppFlow."""
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
                    "❌ Файл credentials.json не найден, и GOOGLE_OAUTH_CLIENT_CONFIG не задан.\n"
                    "   Для настройки: https://console.cloud.google.com/apis/credentials\n"
                    "   Создайте OAuth 2.0 Client ID (Desktop app) и сохраните JSON как credentials.json"
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
                        'https://www.googleapis.com/oauth2/v1/certs',
                    ),
                    'client_secret': raw.get('client_secret'),
                    'redirect_uris': redirect_uris,
                }
            }

        raise Exception(
            "Неподдерживаемый формат credentials.json. Ожидается ключ 'installed' или 'web', "
            "либо плоский OAuth JSON с client_id/client_secret/auth_uri/token_uri."
        )

    def _is_interactive_session(self) -> bool:
        try:
            return bool(sys.stdin and sys.stdin.isatty())
        except Exception:
            return False

    def _print_token_info(self, creds: Credentials) -> None:
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
            print("\n" + "=" * 60)
            print("📋 СКОПИРУЙТЕ ЭТОТ ТОКЕН В main.env (предпочтительно V2):")
            print("=" * 60)
            print(f"GOOGLE_OAUTH_TOKEN_V2={token_v2_json}")
            print(f"GOOGLE_OAUTH_TOKEN={token_json}")
        except Exception as e:
            calendar_logger.warning(f"Unable to serialize credentials for copy/paste: {e}")