"""
Retrieval service for querying indexed documents.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from digest.config import DigestConfig
from digest.index_store import IndexStore
from digest.models import RetrievalResult, SearchResult


class RetrievalService:
    """
    Retrieval API layer for digest system.

    Provides high-level retrieval methods with time-based filtering and
    cross-source aggregation.
    """

    def __init__(self, index_store: IndexStore, config: DigestConfig):
        """
        Initialize retrieval service.

        Args:
            index_store: Index store for searching documents
            config: Digest configuration
        """
        self.index_store = index_store
        self.config = config

    def get_recent_content(
        self,
        topic_id: str,
        hours: Optional[int] = None,
        per_source_limit: int = 20
    ) -> list[RetrievalResult]:
        """
        Get recent content for a topic.

        Args:
            topic_id: Topic to retrieve content for
            hours: Time window in hours (defaults to config.recent_window_hours)
            per_source_limit: Max results per source

        Returns:
            List of retrieval results ordered by recency
        """
        if hours is None:
            hours = self.config.recent_window_hours

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Get all results for topic
        # Use a generic query to retrieve by metadata filters
        results = self.index_store.search(
            query="",  # Empty query for metadata-only filtering
            topic_id=topic_id,
            k=per_source_limit * 10,  # Over-fetch to filter by time
            filters={}
        )

        # Filter by time window
        recent_results = [
            r for r in results
            if r.published_at >= cutoff_time
        ]

        # Group by source and limit per source
        by_source = {}
        for result in recent_results:
            source_id = result.source_id
            if source_id not in by_source:
                by_source[source_id] = []
            if len(by_source[source_id]) < per_source_limit:
                by_source[source_id].append(result)

        # Flatten and sort by published_at descending
        all_results = []
        for source_results in by_source.values():
            all_results.extend(source_results)

        all_results.sort(key=lambda r: r.published_at, reverse=True)

        return [self._search_result_to_retrieval_result(r) for r in all_results]

    def semantic_search(
        self,
        query: str,
        topic_id: str,
        k: int = 8,
        days: Optional[int] = None
    ) -> list[RetrievalResult]:
        """
        Semantic search over indexed content.

        Args:
            query: Search query
            topic_id: Topic filter
            k: Number of results
            days: Optional time window in days

        Returns:
            List of retrieval results ordered by relevance
        """
        filters = {}

        # Add time filter if specified
        if days is not None:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
            # Note: This filtering happens post-retrieval in current implementation
            # For production, consider ChromaDB's where clause

        results = self.index_store.search(
            query=query,
            topic_id=topic_id,
            k=k,
            filters=filters
        )

        # Apply time filter if needed
        if days is not None:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
            results = [r for r in results if r.published_at >= cutoff_time]

        return [self._search_result_to_retrieval_result(r) for r in results]

    def get_source_profile(
        self,
        topic_id: str,
        source_id: str,
        days: Optional[int] = None
    ) -> list[RetrievalResult]:
        """
        Get historical profile for a specific source.

        Args:
            topic_id: Topic filter
            source_id: Source to profile
            days: Time window (defaults to config.source_profile_days)

        Returns:
            List of retrieval results from this source
        """
        if days is None:
            days = self.config.source_profile_days

        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)

        # Search with source filter
        results = self.index_store.search(
            query="",  # Metadata-only
            topic_id=topic_id,
            k=100,  # Get a broad sample
            filters={'source_id': source_id}
        )

        # Filter by time
        recent_results = [
            r for r in results
            if r.published_at >= cutoff_time
        ]

        # Sort by published_at descending
        recent_results.sort(key=lambda r: r.published_at, reverse=True)

        return [self._search_result_to_retrieval_result(r) for r in recent_results]

    def find_related_across_sources(
        self,
        query: str,
        topic_id: str,
        k: int = 12
    ) -> list[RetrievalResult]:
        """
        Find related content across all sources for a topic.

        Args:
            query: Search query
            topic_id: Topic filter
            k: Number of results

        Returns:
            List of retrieval results from multiple sources
        """
        results = self.index_store.search(
            query=query,
            topic_id=topic_id,
            k=k,
            filters={}
        )

        return [self._search_result_to_retrieval_result(r) for r in results]

    def _search_result_to_retrieval_result(self, search_result: SearchResult) -> RetrievalResult:
        """Convert SearchResult to RetrievalResult."""
        return RetrievalResult(
            content=search_result.content,
            source_id=search_result.source_id,
            published_at=search_result.published_at,
            url=search_result.url,
            score=search_result.score,
            metadata=search_result.metadata
        )
