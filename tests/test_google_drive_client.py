from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from google_drive_client import GoogleDriveClient


class GoogleDriveClientTests(unittest.TestCase):
    def test_drive_client_initializes_with_drive_service(self):
        fake_creds = object()
        fake_oauth_instance = MagicMock()
        fake_oauth_instance.authenticate.return_value = fake_creds
        drive_service = MagicMock()

        with patch("google_base_client.GoogleOAuthClient", return_value=fake_oauth_instance), patch(
            "google_drive_client.build", return_value=drive_service
        ) as build_mock, patch.object(GoogleDriveClient, "_find_or_create_folder", return_value="folder-123"):
            client = GoogleDriveClient(credentials_path="custom_credentials.json")

        self.assertIs(client.drive_service, drive_service)
        self.assertEqual(client.notes_folder_id, "folder-123")
        build_mock.assert_called_once_with("drive", "v3", credentials=fake_creds)

    def test_drive_client_uses_drive_file_scope(self):
        self.assertEqual(
            GoogleDriveClient.SCOPES,
            ["https://www.googleapis.com/auth/drive.file"],
        )

    def test_save_note_returns_error_when_folder_not_initialized(self):
        fake_oauth_instance = MagicMock()
        fake_oauth_instance.authenticate.return_value = object()

        with patch("google_base_client.GoogleOAuthClient", return_value=fake_oauth_instance), patch(
            "google_drive_client.build"
        ), patch.object(GoogleDriveClient, "_find_or_create_folder", side_effect=Exception("folder error")):
            client = GoogleDriveClient()

        result = client.save_note("Test Note", "Content")

        self.assertFalse(result["success"])
        self.assertIn("Не удалось инициализировать папку заметок", result["message"])

    def test_resolve_note_title_uses_content_for_generic_title(self):
        fake_oauth_instance = MagicMock()
        fake_oauth_instance.authenticate.return_value = object()

        with patch("google_base_client.GoogleOAuthClient", return_value=fake_oauth_instance), patch(
            "google_drive_client.build"
        ), patch.object(GoogleDriveClient, "_find_or_create_folder", return_value="folder-1"):
            client = GoogleDriveClient()

        resolved = client._resolve_note_title("Без названия", "Купить молоко, хлеб и сыр. Не забыть скидочную карту.")

        self.assertEqual(resolved, "Купить молоко, хлеб и сыр")

    def test_build_note_file_content_has_readable_layout(self):
        fake_oauth_instance = MagicMock()
        fake_oauth_instance.authenticate.return_value = object()

        with patch("google_base_client.GoogleOAuthClient", return_value=fake_oauth_instance), patch(
            "google_drive_client.build"
        ), patch.object(GoogleDriveClient, "_find_or_create_folder", return_value="folder-1"):
            client = GoogleDriveClient()

        body = client._build_note_file_content("Покупки", "Молоко\nХлеб")

        self.assertIn("Покупки", body)
        self.assertIn("Содержание", body)
        self.assertIn("Молоко", body)
        self.assertIn("Хлеб", body)


if __name__ == "__main__":
    unittest.main()
