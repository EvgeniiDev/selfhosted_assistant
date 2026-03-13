"""
YouTube channel source adapter.

Fetches video transcripts via RSS feed (no API key required).
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from digest.source_base import SourceAdapter
from digest.models import RawSourceItem, DigestDocument, SourceConfig, IngestionState
from digest.index_store import compute_content_hash

logger = logging.getLogger(__name__)

_CYRILLIC = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")


def _detect_language(text: str) -> str:
    """Detect language by Cyrillic character ratio."""
    if not text:
        return "en"
    cyrillic_count = sum(1 for c in text if c in _CYRILLIC)
    ratio = cyrillic_count / len(text)
    return "ru" if ratio > 0.15 else "en"


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse ISO 8601 date string from YouTube RSS feed."""
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


class YouTubeSourceAdapter(SourceAdapter):
    """
    Source adapter for YouTube channels.

    Fetches video list via RSS (no API key) and retrieves transcripts
    via youtube-transcript-api.
    """

    RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    def __init__(self, source_config: SourceConfig):
        """
        Initialize YouTube source adapter.

        Args:
            source_config: Source configuration with 'channel_id' and 'slug' fields
        """
        super().__init__(source_config)

        if not source_config.channel_id:
            raise ValueError(
                f"YouTube source {source_config.source_id} missing 'channel_id' field"
            )

        self.channel_id = source_config.channel_id
        self.slug = source_config.slug or source_config.channel_id

    def fetch_items(
        self,
        since_state: Optional[IngestionState] = None,
        lookback_days: int = 7
    ) -> list[RawSourceItem]:
        """
        Fetch new videos from YouTube channel via RSS.

        Args:
            since_state: Previous ingestion state for incremental updates
            lookback_days: Fallback lookback window if no state exists

        Returns:
            List of raw source items with transcript content
        """
        import feedparser
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

        # Determine cutoff date
        if since_state and since_state.last_seen_published_at:
            cutoff = since_state.last_seen_published_at
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        # Fetch RSS feed
        rss_url = self.RSS_URL.format(channel_id=self.channel_id)
        try:
            feed = feedparser.parse(rss_url)
        except Exception as e:
            logger.error(f"Failed to fetch RSS for {self.slug}: {e}")
            return []

        items = []
        for entry in feed.entries:
            # Parse video published date
            published_str = getattr(entry, 'published', None)
            if not published_str:
                continue

            published_at = _parse_rss_date(published_str)
            if published_at is None:
                continue

            # Skip old videos
            if published_at <= cutoff:
                continue

            # Get video ID
            video_id = getattr(entry, 'yt_videoid', None)
            if not video_id:
                # Fallback: extract from entry id
                entry_id = getattr(entry, 'id', '')
                if 'v=' in entry_id:
                    video_id = entry_id.split('v=')[-1]
                else:
                    continue

            video_title = getattr(entry, 'title', video_id)
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            # Fetch transcript
            try:
                transcript_data = YouTubeTranscriptApi.get_transcript(
                    video_id,
                    languages=['ru', 'en']
                )
                transcript_text = " ".join(
                    segment.get('text', '') for segment in transcript_data
                ).strip()

                if not transcript_text:
                    logger.warning(f"Empty transcript for video {video_id} ({self.slug})")
                    continue

                items.append(RawSourceItem(
                    external_id=video_id,
                    published_at=published_at,
                    content=transcript_text,
                    url=video_url,
                    metadata={
                        'title': video_title,
                        'channel': self.slug,
                    }
                ))

            except (TranscriptsDisabled, NoTranscriptFound) as e:
                logger.warning(
                    f"No transcript for video {video_id} ({self.slug}): {e}"
                )
                continue
            except Exception as e:
                logger.warning(
                    f"Error fetching transcript for video {video_id} ({self.slug}): {e}"
                )
                continue

        return items

    def normalize_to_document(
        self,
        item: RawSourceItem,
        ingested_at: datetime
    ) -> DigestDocument:
        """
        Normalize YouTube video item to DigestDocument.

        Args:
            item: Raw source item with transcript content
            ingested_at: Ingestion timestamp

        Returns:
            DigestDocument
        """
        video_id = item.external_id
        doc_id = f"yt:{self.slug}:{video_id}"
        language = _detect_language(item.content)

        return DigestDocument(
            doc_id=doc_id,
            source_type="youtube",
            source_id=self.source_config.source_id,
            external_id=video_id,
            topic_ids=self.source_config.topic_ids,
            published_at=item.published_at,
            ingested_at=ingested_at,
            url=item.url,
            author_label=self.slug,
            language=language,
            content_kind="transcript",
            content_hash=compute_content_hash(item.content),
            content=item.content,
        )
