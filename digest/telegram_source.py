"""
Telegram channel source adapter.
"""

import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Iterator

import requests
from bs4 import BeautifulSoup

from digest.source_base import SourceAdapter
from digest.models import RawSourceItem, DigestDocument, SourceConfig, IngestionState
from digest.index_store import compute_content_hash


# HTTP client setup
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
})

# Text cleaning regexes
_NON_TEXT = re.compile(
    r"[^\u0020-\u007E"  # Basic Latin printable
    r"\u00C0-\u024F"    # Latin Extended-A/B
    r"\u0400-\u04FF"    # Cyrillic
    r"\u0500-\u052F"    # Cyrillic Supplement
    r"\t\n\r]"
)
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_URL = re.compile(r"https?://\S+")


def clean_text(raw: str, keep_urls: bool = False) -> str:
    """Strip emoji, special symbols, optionally URLs, and normalize whitespace."""
    text = raw
    if not keep_urls:
        text = _URL.sub(" ", text)
    text = _NON_TEXT.sub(" ", text)
    # Collapse all newlines into spaces for RAG
    text = text.replace("\n", " ")
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


class TelegramSourceAdapter(SourceAdapter):
    """
    Source adapter for public Telegram channels.

    Scrapes posts via public t.me/s/ web preview endpoint (no API keys required).
    """

    def __init__(self, source_config: SourceConfig):
        """
        Initialize Telegram source adapter.

        Args:
            source_config: Source configuration with 'slug' field
        """
        super().__init__(source_config)

        if not source_config.slug:
            raise ValueError(f"Telegram source {source_config.source_id} missing 'slug' field")

        self.channel_slug = source_config.slug

    def fetch_items(
        self,
        since_state: Optional[IngestionState] = None,
        lookback_days: int = 7
    ) -> list[RawSourceItem]:
        """
        Fetch new posts from Telegram channel.

        Args:
            since_state: Previous ingestion state
            lookback_days: Fallback lookback window if no state

        Returns:
            List of raw source items
        """
        # Determine cutoff date
        if since_state and since_state.last_seen_published_at:
            cutoff = since_state.last_seen_published_at
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        items = []
        last_seen_id = since_state.last_seen_external_id if since_state else None

        try:
            for post_data in self._iter_channel_posts(cutoff):
                message_id = str(post_data['message_id'])

                # Skip if we've already seen this post
                if last_seen_id and message_id <= last_seen_id:
                    continue

                items.append(RawSourceItem(
                    external_id=message_id,
                    published_at=post_data['date'],
                    content=post_data['text_raw'],
                    url=f"https://t.me/s/{self.channel_slug}/{message_id}",
                    metadata={
                        'channel': self.channel_slug
                    }
                ))
        except Exception as e:
            # Log error but continue with what we have
            print(f"Error fetching from {self.channel_slug}: {e}")

        return items

    def normalize_to_document(
        self,
        item: RawSourceItem,
        ingested_at: datetime
    ) -> DigestDocument:
        """
        Normalize Telegram post to DigestDocument.

        Args:
            item: Raw source item
            ingested_at: Ingestion timestamp

        Returns:
            DigestDocument
        """
        # Clean text
        cleaned_content = clean_text(item.content, keep_urls=False)

        # Generate doc_id
        doc_id = f"{self.source_config.source_id}:{item.external_id}"

        return DigestDocument(
            doc_id=doc_id,
            source_type="telegram",
            source_id=self.source_config.source_id,
            external_id=item.external_id,
            topic_ids=self.source_config.topic_ids,
            published_at=item.published_at,
            ingested_at=ingested_at,
            url=item.url,
            author_label=self.channel_slug,
            language="ru",  # Most channels are Russian
            content_kind="post",
            content_hash=compute_content_hash(cleaned_content),
            content=cleaned_content
        )

    def _iter_channel_posts(self, cutoff: datetime) -> Iterator[dict]:
        """
        Iterate through channel posts from newest to oldest.

        Args:
            cutoff: Stop when posts older than this date are reached

        Yields:
            Dictionaries with message_id, date, text_raw
        """
        url = f"https://t.me/s/{self.channel_slug}"
        before_id: Optional[int] = None
        consecutive_errors = 0

        while True:
            req_url = f"{url}?before={before_id}" if before_id else url

            try:
                resp = SESSION.get(req_url, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as exc:
                consecutive_errors += 1
                print(f"[warn] {self.channel_slug}: HTTP error: {exc}")
                if consecutive_errors >= 3:
                    print(f"[error] {self.channel_slug}: 3 consecutive errors, stopping")
                    return
                time.sleep(2.0)
                continue

            consecutive_errors = 0
            posts = self._parse_page(resp.text)

            if not posts:
                return  # No more content

            # Posts are returned in ascending order; walk from newest
            reached_cutoff = False
            for post in reversed(posts):
                if post['date'] < cutoff:
                    reached_cutoff = True
                    continue
                yield post

            if reached_cutoff:
                return  # Gone past requested window

            # Paginate
            oldest_id = min(p['message_id'] for p in posts)
            if before_id is not None and oldest_id >= before_id:
                return  # Stuck, safety exit

            before_id = oldest_id
            time.sleep(0.4)  # Rate limiting

    def _parse_page(self, html: str) -> list[dict]:
        """
        Parse a single page of t.me/s/ HTML.

        Args:
            html: HTML content

        Returns:
            List of {message_id, date, text_raw} dictionaries
        """
        soup = BeautifulSoup(html, "html.parser")
        posts = []

        for msg in soup.select(".tgme_widget_message"):
            # Extract message_id
            post_attr = msg.get("data-post", "")
            try:
                message_id = int(post_attr.split("/")[-1])
            except (ValueError, IndexError):
                continue

            # Extract date
            time_tag = msg.select_one("time[datetime]")
            if not time_tag:
                continue

            try:
                dt = datetime.fromisoformat(time_tag["datetime"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            # Extract text
            text_div = msg.select_one(".tgme_widget_message_text")
            if text_div:
                # Replace <br> with newlines
                for br in text_div.find_all("br"):
                    br.replace_with("\n")
                raw_text = text_div.get_text(separator="\n")
            else:
                raw_text = ""

            posts.append({
                "message_id": message_id,
                "date": dt,
                "text_raw": raw_text
            })

        return posts
