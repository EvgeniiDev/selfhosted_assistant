"""
Data models for the Topic-Aware Digest RAG system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class DigestDocument:
    """
    Unified document model for all ingested content.

    This model ensures consistent metadata tracking across different sources
    (Telegram, YouTube) and enables reliable deduplication and retrieval.
    """
    doc_id: str                     # e.g., "tg:ProfitGate:12345"
    source_type: str                # "telegram" | "youtube"
    source_id: str                  # Channel slug or YouTube channel ID
    external_id: str                # Message ID or video ID
    topic_ids: list[str]            # e.g., ["investing"]
    published_at: datetime          # Original publication time
    ingested_at: datetime           # When ingested into our system
    url: str                        # Link to original content
    author_label: str               # Display name for the source
    language: str                   # "ru" | "en"
    content_kind: str               # "post" | "video" | "transcript"
    content_hash: str               # SHA256 for deduplication
    content: str                    # Actual text content
    chunk_id: Optional[str] = None  # For chunked documents: "tg:ProfitGate:12345#chunk-0"
    parent_doc_id: Optional[str] = None  # Reference to parent document if chunked


@dataclass
class RawSourceItem:
    """
    Raw item fetched from a source before normalization.
    """
    external_id: str
    published_at: datetime
    content: str
    url: str
    metadata: dict = field(default_factory=dict)


@dataclass
class SourceConfig:
    """
    Configuration for a single content source.
    """
    source_id: str          # e.g., "telegram:VectorCapital_Investments"
    type: str               # "telegram" | "youtube"
    topic_ids: list[str]    # Topics this source covers
    enabled: bool           # Whether to ingest from this source
    # Type-specific fields stored in metadata
    slug: Optional[str] = None          # For Telegram channels
    channel_id: Optional[str] = None    # For YouTube channels
    path: Optional[str] = None          # For directory-based PDF sources


@dataclass
class TopicConfig:
    """
    Configuration for a topic category.
    """
    topic_id: str
    label: str              # Display name
    query_aliases: list[str]  # Keywords for matching user queries


@dataclass
class DigestConfig:
    """
    Main configuration for the digest system.
    """
    topics: dict[str, TopicConfig]
    sources: list[SourceConfig]
    embedding_model: str
    chroma_path: str
    state_path: str
    digest_output_path: str
    recent_window_hours: int
    source_profile_days: int
    ingestion_interval_minutes: int
    digest_schedule: str
    digest_chat_id: Optional[int]


@dataclass
class IngestionState:
    """
    Per-source ingestion checkpoint state.
    """
    last_seen_external_id: str
    last_seen_published_at: datetime
    last_success_at: datetime


@dataclass
class SearchResult:
    """
    Single search result from IndexStore.
    """
    doc_id: str
    content: str
    source_id: str
    published_at: datetime
    url: str
    score: float
    metadata: dict


@dataclass
class RetrievalResult:
    """
    Retrieval result with source attribution for Q&A.
    """
    content: str
    source_id: str
    published_at: datetime
    url: str
    score: float
    metadata: dict


@dataclass
class EvidenceSnippet:
    """
    Evidence snippet supporting an answer.
    """
    text: str
    source_id: str
    source_label: str
    published_at: datetime
    url: str
    relevance_score: float


@dataclass
class QAResponse:
    """
    Response to a user's Q&A query.
    """
    answer: str                         # Main answer
    evidence: list[EvidenceSnippet]     # Supporting snippets
    sources: list[str]                  # Unique source URLs
    confidence: float                   # 0-1
    needs_clarification: bool           # Whether question is unclear
    suggested_topics: list[str]         # If topic unclear


@dataclass
class ContentCluster:
    """
    Cluster of similar content from different sources (for near-dedup).
    """
    representative_text: str
    source_ids: list[str]
    doc_ids: list[str]
    similarity_score: float


@dataclass
class SourceDigest:
    """
    Digest for a single source.
    """
    source_id: str
    source_label: str
    topic_id: str
    generated_at: datetime
    timeframe_hours: int
    key_points: list[str]
    themes: list[str]
    author_stance: str      # Overall stance/perspective of the author


@dataclass
class TopicDigest:
    """
    Cross-source digest for a topic.
    """
    topic_id: str
    topic_label: str
    generated_at: datetime
    timeframe_hours: int
    source_digests: list[SourceDigest]
    consensus_points: list[str]         # What sources agree on
    divergence_points: list[str]        # Where sources disagree
    new_developments: list[str]         # New vs ongoing narratives
    summary: str                        # Overall synthesis
