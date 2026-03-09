"""Base class for Google API clients with shared OAuth credentials wiring."""
from abc import ABC, abstractmethod
from typing import Optional, List
from google.oauth2.credentials import Credentials
from google_oauth_client import GoogleOAuthClient


class GoogleBaseClient(ABC):
    """Base class for Google API clients.

    Subclasses declare SCOPES and implement _setup_services(creds) to build
    and assign their service objects from authenticated credentials.
    """

    SCOPES: List[str] = []

    def __init__(self, credentials_path: str = "credentials.json", oauth_client: Optional[GoogleOAuthClient] = None):
        self.credentials_path = credentials_path
        self.creds: Optional[Credentials] = None
        self.oauth_client = oauth_client or GoogleOAuthClient(
            # Use one shared scope set for all Google clients to keep a single OAuth token.
            scopes=GoogleOAuthClient.DEFAULT_SCOPES,
            credentials_path=credentials_path,
        )
        self.creds = self.oauth_client.authenticate()
        self._setup_services(self.creds)

    @abstractmethod
    def _setup_services(self, creds: Credentials) -> None:
        """Build and assign service objects from authenticated credentials."""
