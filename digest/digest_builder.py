"""
Digest builder for generating topic-based digests.
"""

from datetime import datetime, timezone
from typing import Optional

from llm_core.contracts import LLMGateway, LLMRequest

from digest.retrieval_service import RetrievalService
from digest.models import (
    SourceDigest,
    TopicDigest,
    ContentCluster,
    RetrievalResult
)


class DigestBuilder:
    """
    Multi-layer digest generation system.

    Builds:
    - Per-source digests
    - Topic-level synthesis
    - Duplicate detection and clustering
    """

    def __init__(self, retrieval_service: RetrievalService, gateway: Optional[LLMGateway] = None):
        """
        Initialize digest builder.

        Args:
            retrieval_service: Retrieval service for fetching content
            gateway: LLM gateway for text generation (optional for basic mode)
        """
        self.retrieval_service = retrieval_service
        self.gateway = gateway

    def build_source_digest(
        self,
        source_id: str,
        topic_id: str,
        hours: int = 24
    ) -> SourceDigest:
        """
        Build digest for a single source.

        Args:
            source_id: Source identifier
            topic_id: Topic filter
            hours: Time window in hours

        Returns:
            SourceDigest
        """
        # Get content from source
        results = self.retrieval_service.get_source_profile(
            topic_id=topic_id,
            source_id=source_id,
            days=hours // 24 or 1
        )

        if not results:
            return SourceDigest(
                source_id=source_id,
                source_label=source_id.split(':')[-1],
                topic_id=topic_id,
                generated_at=datetime.now(timezone.utc),
                timeframe_hours=hours,
                key_points=[],
                themes=[],
                author_stance="No recent content"
            )

        # Extract key information
        key_points = self._extract_key_points(results)
        themes = self._extract_themes(results)
        stance = self._determine_stance(results)

        return SourceDigest(
            source_id=source_id,
            source_label=source_id.split(':')[-1],
            topic_id=topic_id,
            generated_at=datetime.now(timezone.utc),
            timeframe_hours=hours,
            key_points=key_points,
            themes=themes,
            author_stance=stance
        )

    def build_topic_digest(
        self,
        topic_id: str,
        hours: int = 24
    ) -> TopicDigest:
        """
        Build cross-source digest for a topic.

        Args:
            topic_id: Topic identifier
            hours: Time window in hours

        Returns:
            TopicDigest
        """
        # Get topic config
        topic_config = self.retrieval_service.config.topics.get(topic_id)
        if not topic_config:
            raise ValueError(f"Unknown topic: {topic_id}")

        # Get all sources for this topic
        from digest.config import get_sources_by_topic
        sources = get_sources_by_topic(self.retrieval_service.config, topic_id)

        # Build digest for each source
        source_digests = []
        for source in sources:
            try:
                digest = self.build_source_digest(
                    source_id=source.source_id,
                    topic_id=topic_id,
                    hours=hours
                )
                source_digests.append(digest)
            except Exception as e:
                print(f"Error building digest for {source.source_id}: {e}")

        # Synthesize across sources
        consensus_points = self._find_consensus(source_digests)
        divergence_points = self._find_divergences(source_digests)
        new_developments = self._identify_new_developments(topic_id, hours)

        # Generate summary
        summary = self._generate_topic_summary(
            topic_config.label,
            source_digests,
            consensus_points,
            divergence_points
        )

        return TopicDigest(
            topic_id=topic_id,
            topic_label=topic_config.label,
            generated_at=datetime.now(timezone.utc),
            timeframe_hours=hours,
            source_digests=source_digests,
            consensus_points=consensus_points,
            divergence_points=divergence_points,
            new_developments=new_developments,
            summary=summary
        )

    def detect_duplicates(
        self,
        results: list[RetrievalResult],
        threshold: float = 0.8
    ) -> list[ContentCluster]:
        """
        Detect near-duplicate content across sources.

        Args:
            results: Retrieval results to cluster
            threshold: Similarity threshold for clustering

        Returns:
            List of content clusters
        """
        # Simplified implementation: group by exact content hash
        # In production, use semantic similarity
        clusters_dict = {}

        for result in results:
            content_key = result.content[:100]  # Use prefix as key

            if content_key not in clusters_dict:
                clusters_dict[content_key] = {
                    'representative_text': result.content,
                    'source_ids': [],
                    'doc_ids': []
                }

            cluster = clusters_dict[content_key]
            if result.source_id not in cluster['source_ids']:
                cluster['source_ids'].append(result.source_id)
            cluster['doc_ids'].append(result.metadata.get('doc_id', ''))

        # Convert to ContentCluster objects
        clusters = []
        for cluster_data in clusters_dict.values():
            if len(cluster_data['source_ids']) > 1:  # Only multi-source clusters
                clusters.append(ContentCluster(
                    representative_text=cluster_data['representative_text'][:200],
                    source_ids=cluster_data['source_ids'],
                    doc_ids=cluster_data['doc_ids'],
                    similarity_score=1.0  # Simplified
                ))

        return clusters

    def _extract_key_points(self, results: list[RetrievalResult]) -> list[str]:
        """Extract key points from content."""
        # Simplified: take first sentence from top results
        points = []
        for result in results[:5]:
            sentences = result.content.split('.')
            if sentences:
                point = sentences[0].strip()
                if len(point) > 20 and point not in points:
                    points.append(point)

        return points[:10]

    def _extract_themes(self, results: list[RetrievalResult]) -> list[str]:
        """Extract themes from content."""
        # Simplified: return placeholder
        return ["Обзор рынка", "Инвестиционные возможности"]

    def _determine_stance(self, results: list[RetrievalResult]) -> str:
        """Determine author's stance from content."""
        # Simplified: return placeholder
        return "Neutral to positive outlook on market conditions"

    def _find_consensus(self, digests: list[SourceDigest]) -> list[str]:
        """Find consensus points across sources."""
        # Simplified: look for common key points
        all_points = []
        for digest in digests:
            all_points.extend(digest.key_points)

        # Find points mentioned by multiple sources
        point_counts = {}
        for point in all_points:
            point_counts[point] = point_counts.get(point, 0) + 1

        consensus = [
            point for point, count in point_counts.items()
            if count > 1
        ]

        return consensus[:5]

    def _find_divergences(self, digests: list[SourceDigest]) -> list[str]:
        """Find divergence points across sources."""
        # Simplified: return placeholder
        divergences = []

        for i, digest1 in enumerate(digests):
            for digest2 in digests[i+1:]:
                if digest1.author_stance != digest2.author_stance:
                    divergences.append(
                        f"{digest1.source_label} vs {digest2.source_label}: Different perspectives on market outlook"
                    )

        return divergences[:3]

    def _identify_new_developments(self, topic_id: str, hours: int) -> list[str]:
        """Identify new vs ongoing narratives."""
        # Simplified: return placeholder
        return ["Продолжение обсуждения текущих рыночных трендов"]

    def _generate_topic_summary(
        self,
        topic_label: str,
        source_digests: list[SourceDigest],
        consensus: list[str],
        divergences: list[str]
    ) -> str:
        """Generate overall topic summary."""
        summary_parts = [f"Дайджест: {topic_label}"]

        if consensus:
            summary_parts.append(f"\n\nКонсенсус ({len(consensus)} пунктов):")
            for point in consensus[:3]:
                summary_parts.append(f"- {point}")

        if divergences:
            summary_parts.append(f"\n\nРазличия во мнениях:")
            for div in divergences[:2]:
                summary_parts.append(f"- {div}")

        summary_parts.append(f"\n\nОхвачено источников: {len(source_digests)}")

        return "\n".join(summary_parts)
