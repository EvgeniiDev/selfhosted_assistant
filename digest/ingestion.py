"""
Batch ingestion orchestrator for digest system.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from llama_index.core.node_parser import SentenceSplitter

from digest.config import DigestConfig
from digest.models import DigestDocument, IngestionState
from digest.source_base import SourceAdapter
from digest.telegram_source import TelegramSourceAdapter
from digest.index_store import IndexStore, compute_content_hash


class IngestionOrchestrator:
    """
    Orchestrates batch ingestion from multiple sources.

    Handles:
    - Loading/saving ingestion state
    - Fetching new items from sources
    - Chunking long content
    - Deduplication via content_hash
    - Upserting to index store
    """

    def __init__(self, config: DigestConfig, index_store: IndexStore):
        """
        Initialize ingestion orchestrator.

        Args:
            config: Digest configuration
            index_store: Index store for document storage
        """
        self.config = config
        self.index_store = index_store
        self.state_path = Path(config.state_path)

        # Initialize chunker
        self.chunker = SentenceSplitter(
            chunk_size=500,
            chunk_overlap=50
        )

        # Create state directory if needed
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def run_ingestion(self, lookback_days: int = 7) -> dict:
        """
        Run batch ingestion from all enabled sources.

        Args:
            lookback_days: Fallback lookback window if no state exists

        Returns:
            Statistics dictionary with ingestion results
        """
        stats = {
            'sources_processed': 0,
            'items_fetched': 0,
            'documents_created': 0,
            'chunks_created': 0,
            'added': 0,
            'updated': 0,
            'skipped': 0,
            'errors': []
        }

        # Load ingestion state
        state = self._load_state()

        # Process each enabled source
        for source_config in self.config.sources:
            if not source_config.enabled:
                continue

            try:
                source_stats = self._process_source(
                    source_config,
                    state.get(source_config.source_id),
                    lookback_days
                )

                stats['sources_processed'] += 1
                stats['items_fetched'] += source_stats['items_fetched']
                stats['documents_created'] += source_stats['documents_created']
                stats['chunks_created'] += source_stats['chunks_created']
                stats['added'] += source_stats['added']
                stats['updated'] += source_stats['updated']
                stats['skipped'] += source_stats['skipped']

                # Update state for this source
                if source_stats['last_seen_id'] and source_stats['last_seen_date']:
                    state[source_config.source_id] = {
                        'last_seen_external_id': source_stats['last_seen_id'],
                        'last_seen_published_at': source_stats['last_seen_date'].isoformat(),
                        'last_success_at': datetime.now(timezone.utc).isoformat()
                    }

            except Exception as e:
                error_msg = f"Error processing source {source_config.source_id}: {e}"
                stats['errors'].append(error_msg)
                print(f"[error] {error_msg}")

        # Save updated state
        self._save_state(state)

        return stats

    def _process_source(
        self,
        source_config,
        prev_state: Optional[dict],
        lookback_days: int
    ) -> dict:
        """
        Process a single source.

        Args:
            source_config: Source configuration
            prev_state: Previous ingestion state for this source
            lookback_days: Lookback window

        Returns:
            Statistics for this source
        """
        stats = {
            'items_fetched': 0,
            'documents_created': 0,
            'chunks_created': 0,
            'added': 0,
            'updated': 0,
            'skipped': 0,
            'last_seen_id': None,
            'last_seen_date': None
        }

        # Create source adapter
        adapter = self._create_adapter(source_config)

        # Convert prev_state to IngestionState if exists
        since_state = None
        if prev_state:
            since_state = IngestionState(
                last_seen_external_id=prev_state['last_seen_external_id'],
                last_seen_published_at=datetime.fromisoformat(prev_state['last_seen_published_at']),
                last_success_at=datetime.fromisoformat(prev_state['last_success_at'])
            )

        # Fetch new items
        raw_items = adapter.fetch_items(since_state=since_state, lookback_days=lookback_days)
        stats['items_fetched'] = len(raw_items)

        if not raw_items:
            return stats

        # Normalize and chunk documents
        all_documents = []
        ingested_at = datetime.now(timezone.utc)

        for item in raw_items:
            # Normalize to DigestDocument
            doc = adapter.normalize_to_document(item, ingested_at)
            stats['documents_created'] += 1

            # Track latest item
            if stats['last_seen_date'] is None or doc.published_at > stats['last_seen_date']:
                stats['last_seen_date'] = doc.published_at
                stats['last_seen_id'] = doc.external_id

            # Chunk if content is long
            if len(doc.content) > 600:  # Chunk threshold
                chunks = self._chunk_document(doc)
                all_documents.extend(chunks)
                stats['chunks_created'] += len(chunks)
            else:
                all_documents.append(doc)

        # Upsert to index store
        if all_documents:
            upsert_stats = self.index_store.upsert_documents(all_documents)
            stats['added'] = upsert_stats['added']
            stats['updated'] = upsert_stats['updated']
            stats['skipped'] = upsert_stats['skipped']

        return stats

    def _chunk_document(self, doc: DigestDocument) -> list[DigestDocument]:
        """
        Chunk a long document into smaller pieces.

        Args:
            doc: Document to chunk

        Returns:
            List of chunked documents
        """
        chunks_text = self.chunker.split_text(doc.content)
        chunk_docs = []

        for idx, chunk_text in enumerate(chunks_text):
            chunk_id = f"{doc.doc_id}#chunk-{idx}"

            chunk_doc = DigestDocument(
                doc_id=chunk_id,
                source_type=doc.source_type,
                source_id=doc.source_id,
                external_id=doc.external_id,
                topic_ids=doc.topic_ids,
                published_at=doc.published_at,
                ingested_at=doc.ingested_at,
                url=doc.url,
                author_label=doc.author_label,
                language=doc.language,
                content_kind=doc.content_kind,
                content_hash=compute_content_hash(chunk_text),
                content=chunk_text,
                chunk_id=chunk_id,
                parent_doc_id=doc.doc_id
            )

            chunk_docs.append(chunk_doc)

        return chunk_docs

    def _create_adapter(self, source_config) -> SourceAdapter:
        """
        Create appropriate source adapter based on type.

        Args:
            source_config: Source configuration

        Returns:
            SourceAdapter instance
        """
        if source_config.type == "telegram":
            return TelegramSourceAdapter(source_config)
        elif source_config.type == "youtube":
            from digest.youtube_source import YouTubeSourceAdapter
            return YouTubeSourceAdapter(source_config)
        else:
            raise ValueError(f"Unsupported source type: {source_config.type}")

    def _load_state(self) -> dict:
        """
        Load ingestion state from file.

        Returns:
            State dictionary (source_id -> state dict)
        """
        if not self.state_path.exists():
            return {}

        try:
            with open(self.state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[warn] Error loading ingestion state: {e}")
            return {}

    def _save_state(self, state: dict):
        """
        Save ingestion state to file.

        Args:
            state: State dictionary to save
        """
        try:
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[error] Error saving ingestion state: {e}")
