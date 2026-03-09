from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from google_calendar_client import GoogleCalendarClient
from google_drive_client import GoogleDriveClient
from google_oauth_client import GoogleOAuthClient


class GoogleApiClientsSetupTests(unittest.TestCase):
    def test_calendar_client_initializes_calendar_and_tasks_services_from_shared_oauth(self):
        fake_creds = object()
        fake_oauth_instance = MagicMock()
        fake_oauth_instance.authenticate.return_value = fake_creds
        calendar_service = object()
        tasks_service = object()
        expected_default_scopes = ["scope://default-a", "scope://default-b"]

        with patch("google_base_client.GoogleOAuthClient", return_value=fake_oauth_instance) as oauth_cls, patch(
            "google_calendar_client.build", side_effect=[calendar_service, tasks_service]
        ) as build_mock:
            oauth_cls.DEFAULT_SCOPES = expected_default_scopes
            client = GoogleCalendarClient(credentials_path="custom_credentials.json")

        oauth_cls.assert_called_once_with(
            scopes=expected_default_scopes,
            credentials_path="custom_credentials.json",
        )
        self.assertEqual(build_mock.call_count, 2)
        build_mock.assert_any_call("calendar", "v3", credentials=fake_creds)
        build_mock.assert_any_call("tasks", "v1", credentials=fake_creds)
        self.assertIs(client.calendar_service, calendar_service)
        self.assertIs(client.tasks_service, tasks_service)

    def test_notes_client_initializes_drive_service_from_shared_oauth(self):
        fake_creds = object()
        fake_oauth_instance = MagicMock()
        fake_oauth_instance.authenticate.return_value = fake_creds
        drive_service = object()
        expected_default_scopes = ["scope://default-a", "scope://default-b"]

        with patch("google_base_client.GoogleOAuthClient", return_value=fake_oauth_instance) as oauth_cls, patch(
            "google_drive_client.build", return_value=drive_service
        ) as build_mock, patch.object(GoogleDriveClient, "_find_or_create_folder", return_value="folder-1"):
            oauth_cls.DEFAULT_SCOPES = expected_default_scopes
            client = GoogleDriveClient(credentials_path="drive_credentials.json")

        oauth_cls.assert_called_once_with(
            scopes=expected_default_scopes,
            credentials_path="drive_credentials.json",
        )
        build_mock.assert_called_once_with("drive", "v3", credentials=fake_creds)
        self.assertIs(client.drive_service, drive_service)


if __name__ == "__main__":
    unittest.main()