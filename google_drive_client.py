"""Client for Google Drive API to store notes as files.

Uses https://www.googleapis.com/auth/drive.file scope for secure file access.
"""
from typing import Dict, Any, Optional
from datetime import datetime
import re
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_base_client import GoogleBaseClient
from google_oauth_client import GoogleOAuthClient
from logger import calendar_logger


class GoogleDriveClient(GoogleBaseClient):
    """Client for Google Drive API to manage notes as files."""

    SCOPES = ['https://www.googleapis.com/auth/drive.file']

    NOTES_FOLDER_NAME = "Assistant Notes"
    _GENERIC_TITLES = {"", "без названия", "заметка", "note", "notes"}

    def __init__(self, credentials_path: str = "credentials.json", oauth_client: Optional[GoogleOAuthClient] = None):
        self.drive_service = None
        self.notes_folder_id = None
        super().__init__(credentials_path, oauth_client=oauth_client)
        self._ensure_notes_folder()

    def _setup_services(self, creds: Credentials) -> None:
        self.drive_service = build('drive', 'v3', credentials=creds)

    def _ensure_notes_folder(self) -> None:
        """Ensures the notes folder exists in Google Drive, creating if necessary."""
        try:
            folder_id = self._find_or_create_folder(self.NOTES_FOLDER_NAME)
            self.notes_folder_id = folder_id
            calendar_logger.info(f"GoogleDriveClient: notes folder ID = {folder_id}")
        except Exception as e:
            calendar_logger.warning(f"GoogleDriveClient: failed to ensure notes folder: {e}")
            self.notes_folder_id = None

    def _find_or_create_folder(self, folder_name: str) -> str:
        """Find folder by name in Drive root, or create if doesn't exist."""
        try:
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = (
                self.drive_service.files()
                .list(q=query, spaces="drive", fields="files(id, name)", pageSize=1)
                .execute()
            )
            files = results.get('files', [])

            if files:
                return files[0]['id']

            calendar_logger.info(f"GoogleDriveClient: folder '{folder_name}' not found, creating...")
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
            }
            folder = self.drive_service.files().create(body=folder_metadata, fields='id').execute()
            folder_id = folder['id']
            calendar_logger.info(f"GoogleDriveClient: created folder '{folder_name}' with ID {folder_id}")
            return folder_id
        except Exception as e:
            raise Exception(f"Failed to find or create folder '{folder_name}': {e}")

    def save_note(self, title: str, content: str) -> Optional[Dict[str, Any]]:
        """Save note as a text file in the notes folder."""
        if not self.notes_folder_id:
            return {
                'success': False,
                'error': 'Notes folder not initialized',
                'message': 'Не удалось инициализировать папку заметок',
            }

        try:
            from googleapiclient.http import MediaInMemoryUpload

            resolved_title = self._resolve_note_title(title, content)
            filename = f"{self._safe_filename(resolved_title)}.txt"
            body_text = self._build_note_file_content(resolved_title, content)

            file_metadata = {
                'name': filename,
                'mimeType': 'text/plain',
                'parents': [self.notes_folder_id],
            }

            media = MediaInMemoryUpload(body_text.encode('utf-8'), mimetype='text/plain')
            file = (
                self.drive_service.files()
                .create(body=file_metadata, media_body=media, fields='id, name, webViewLink, createdTime')
                .execute()
            )

            file_id = file['id']
            web_link = file.get('webViewLink', '')

            result = {
                'success': True,
                'file_id': file_id,
                'title': resolved_title,
                'file_name': file.get('name', filename),
                'created_at': file.get('createdTime', ''),
                'web_link': web_link,
                'message': f"Заметка '{resolved_title}' сохранена",
            }
            calendar_logger.info(f"GoogleDriveClient.save_note OK: {file_id}")
            return result

        except Exception as e:
            result = {
                'success': False,
                'error': str(e),
                'message': f"Ошибка при сохранении заметки: {e}",
            }
            calendar_logger.log_error(e, "google_drive_client.save_note")
            return result

    def _resolve_note_title(self, title: str, content: str) -> str:
        normalized_title = (title or '').strip()
        if normalized_title.lower() not in self._GENERIC_TITLES:
            return normalized_title

        cleaned_content = ' '.join((content or '').split())
        if not cleaned_content:
            return 'Новая заметка'

        primary_chunk = re.split(r'[.!?\n]', cleaned_content, maxsplit=1)[0].strip()
        candidate = primary_chunk or cleaned_content
        if len(candidate) > 60:
            candidate = candidate[:57].rstrip() + '...'
        return candidate or 'Новая заметка'

    def _safe_filename(self, title: str) -> str:
        filename = re.sub(r'[\\/:*?"<>|]', ' ', title).strip()
        filename = re.sub(r'\s+', ' ', filename)
        return filename[:100] or 'Новая заметка'

    def _build_note_file_content(self, title: str, content: str) -> str:
        body = (content or '').strip() or '(пустая заметка)'
        created_local = datetime.now().strftime('%d.%m.%Y %H:%M')
        return (
            f"{title}\n"
            f"{'=' * len(title)}\n\n"
            f"Сохранено ассистентом: {created_local}\n\n"
            "Содержание\n"
            "----------\n"
            f"{body}\n"
        )

    def list_notes(self, page_size: int = 10) -> Optional[Dict[str, Any]]:
        """List notes (files) from the notes folder."""
        if not self.notes_folder_id:
            return {
                'success': False,
                'error': 'Notes folder not initialized',
                'message': 'Не удалось инициализировать папку заметок',
            }

        try:
            query = f"'{self.notes_folder_id}' in parents and trashed=false"
            results = (
                self.drive_service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="files(id, name, createdTime, webViewLink, mimeType)",
                    pageSize=page_size,
                    orderBy="createdTime desc",
                )
                .execute()
            )
            files = results.get('files', [])
            calendar_logger.info(f"GoogleDriveClient.list_notes: fetched {len(files)} notes")
            return {'success': True, 'files': files}
        except Exception as e:
            result = {
                'success': False,
                'error': str(e),
                'message': f"Ошибка при получении заметок: {e}",
            }
            calendar_logger.log_error(e, "google_drive_client.list_notes")
            return result
