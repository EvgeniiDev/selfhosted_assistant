"""
Base interface for source adapters.
"""

from abc import ABC, abstractmethod
from typing import Optional

from digest.models import RawSourceItem, DigestDocument, SourceConfig, IngestionState


class SourceAdapter(ABC):
    """
    Abstract base class for content source adapters.

    Each adapter implements fetching and normalization for a specific source type
    (Telegram, YouTube, etc.)
    """

    def __init__(self, source_config: SourceConfig):
        """
        Initialize source adapter.

        Args:
            source_config: Configuration for this source
        """
        self.source_config = source_config

    @abstractmethod
    def fetch_items(
        self,
        since_state: Optional[IngestionState] = None,
        lookback_days: int = 7
    ) -> list[RawSourceItem]:
        """
        Fetch new items from the source.

        Args:
            since_state: Previous ingestion state (for incremental updates)
            lookback_days: How many days back to fetch if no state exists

        Returns:
            List of raw source items
        """
        pass

    @abstractmethod
    def normalize_to_document(
        self,
        item: RawSourceItem,
        ingested_at
) -> DigestDocument:
        """
        Normalize a raw source item to DigestDocument format.

        Args:
            item: Raw source item
            ingested_at: Timestamp when item was ingested

        Returns:
            DigestDocument
        """
        pass

    def get_source_id(self) -> str:
        """Get source identifier."""
        return self.source_config.source_id

    def get_source_type(self) -> str:
        """Get source type."""
        return self.source_config.type

    def is_enabled(self) -> bool:
        """Check if source is enabled."""
        return self.source_config.enabled
