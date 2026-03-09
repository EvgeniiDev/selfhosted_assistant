from __future__ import annotations

import base64
import json
import types
import unittest
from unittest.mock import MagicMock, patch

from google.oauth2.credentials import Credentials

from google_base_client import GoogleBaseClient
from google_oauth_client import GoogleOAuthClient


class _ScopedBaseClient(GoogleBaseClient):
    SCOPES = ["scope://calendar", "scope://tasks"]

    def _setup_services(self, creds: Credentials) -> None:
        self.received_creds = creds


class _DefaultScopeBaseClient(GoogleBaseClient):
    SCOPES = []

    def _setup_services(self, creds: Credentials) -> None:
        self.received_creds = creds


class GoogleBaseClientTests(unittest.TestCase):
    def test_base_client_uses_shared_default_scopes_and_wires_credentials(self):
        fake_oauth = MagicMock()
        fake_creds = object()
        fake_oauth.authenticate.return_value = fake_creds
        expected_default_scopes = ["scope://default-a", "scope://default-b"]

        with patch("google_base_client.GoogleOAuthClient", return_value=fake_oauth) as oauth_cls:
            oauth_cls.DEFAULT_SCOPES = expected_default_scopes
            client = _ScopedBaseClient(credentials_path="custom_credentials.json")

        oauth_cls.assert_called_once_with(
            scopes=expected_default_scopes,
            credentials_path="custom_credentials.json",
        )
        self.assertIs(client.creds, fake_creds)
        self.assertIs(client.received_creds, fake_creds)

    def test_base_client_uses_default_scopes_when_subclass_scopes_empty(self):
        fake_oauth = MagicMock()
        fake_creds = object()
        fake_oauth.authenticate.return_value = fake_creds
        expected_default_scopes = ["scope://default-a", "scope://default-b"]

        with patch("google_base_client.GoogleOAuthClient", return_value=fake_oauth) as oauth_cls:
            oauth_cls.DEFAULT_SCOPES = expected_default_scopes
            _DefaultScopeBaseClient()

        oauth_cls.assert_called_once_with(
            scopes=expected_default_scopes,
            credentials_path="credentials.json",
        )

    def test_authenticate_reuses_cached_credentials_when_scopes_match(self):
        second = GoogleOAuthClient(scopes=["scope://x"])

        fake_creds = MagicMock()

        GoogleOAuthClient._SHARED_CREDS = fake_creds
        try:
            with patch.object(second, "_can_use_credentials", return_value=True), patch.object(
                second, "_load_credentials_from_env"
            ) as from_env, patch.object(
                second, "_authenticate_auto"
            ) as auto_auth:
                result = second.authenticate()

            self.assertIs(result, fake_creds)
            from_env.assert_not_called()
            auto_auth.assert_not_called()
        finally:
            GoogleOAuthClient._SHARED_CREDS = None


class GoogleOAuthClientTests(unittest.TestCase):
    def test_authenticate_returns_valid_env_credentials(self):
        client = GoogleOAuthClient(scopes=["scope://x"])
        fake_creds = types.SimpleNamespace(
            refresh_token=None,
            valid=True,
            expired=False,
            token="access-token",
        )

        with patch.object(client, "_load_credentials_from_env", return_value=fake_creds), patch.object(
            client, "_authenticate_auto", return_value="fallback"
        ) as auto_auth:
            result = client.authenticate()

        self.assertIs(result, fake_creds)
        auto_auth.assert_not_called()

    def test_authenticate_falls_back_to_interactive_when_no_env_credentials(self):
        client = GoogleOAuthClient(scopes=["scope://x"])
        fallback_creds = object()

        with patch.object(client, "_load_credentials_from_env", return_value=None), patch.object(
            client, "_authenticate_auto", return_value=fallback_creds
        ) as auto_auth:
            result = client.authenticate()

        self.assertIs(result, fallback_creds)
        auto_auth.assert_called_once_with()

    def test_parse_json_env_value_supports_base64_prefix(self):
        client = GoogleOAuthClient(scopes=["scope://x"])
        payload = {"client_id": "id", "client_secret": "secret"}
        encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

        parsed = client._parse_json_env_value(f"base64:{encoded}", "TEST_ENV")

        self.assertEqual(parsed, payload)

    def test_credentials_from_token_v2_accepts_authorized_user_wrapper(self):
        client = GoogleOAuthClient(scopes=["scope://calendar", "scope://tasks"])
        token_payload = {
            "authorized_user": {
                "client_id": "test-client",
                "client_secret": "test-secret",
                "refresh_token": "refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "access_token": "access-token",
            }
        }

        creds = client._credentials_from_token_v2(json.dumps(token_payload))

        self.assertIsInstance(creds, Credentials)
        self.assertEqual(creds.client_id, "test-client")
        self.assertEqual(creds.client_secret, "test-secret")
        self.assertEqual(creds.refresh_token, "refresh-token")

    def test_credentials_from_token_v2_requires_mandatory_fields(self):
        client = GoogleOAuthClient(scopes=["scope://x"])
        broken_payload = {
            "client_id": "test-client",
            "client_secret": "test-secret",
        }

        with self.assertRaises(Exception) as err:
            client._credentials_from_token_v2(json.dumps(broken_payload))

        self.assertIn("отсутствуют обязательные поля", str(err.exception))


if __name__ == "__main__":
    unittest.main()