"""
Tests for digest index store with ChromaDB.

Note: These tests require ChromaDB and embedding dependencies to be installed.
"""

import unittest
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path

from digest.models import DigestDocument, DigestConfig, TopicConfig, SourceConfig
from digest.index_store import IndexStore, compute_content_hash


class IndexStoreTests(unittest.TestCase):
    """Test index store operations."""

    def setUp(self):
        """Set up test fixtures."""
        # Create temporary directory for ChromaDB
        self.test_dir = tempfile.mkdtemp()

        # Create minimal config
        self.config = DigestConfig(
            topics={"test": TopicConfig(topic_id="test", label="Test", query_aliases=[])},
            sources=[],
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",  # Small fast model for testing
            chroma_path=str(Path(self.test_dir) / "chroma"),
            state_path=str(Path(self.test_dir) / "state.json"),
            digest_output_path=str(Path(self.test_dir) / "digests"),
            recent_window_hours=36,
            source_profile_days=60,
            ingestion_interval_minutes=60,
            digest_schedule="0 21 * * *",
            digest_chat_id=None
        )

    def tearDown(self):
        """Clean up test fixtures."""
        # Remove temporary directory
        if Path(self.test_dir).exists():
            shutil.rmtree(self.test_dir)

    def test_compute_content_hash(self):
        """Test content hash computation."""
        content1 = "Test content"
        content2 = "Test content"
        content3 = "Different content"

        hash1 = compute_content_hash(content1)
        hash2 = compute_content_hash(content2)
        hash3 = compute_content_hash(content3)

        # Same content should produce same hash
        self.assertEqual(hash1, hash2)
        # Different content should produce different hash
        self.assertNotEqual(hash1, hash3)
        # Hash should be SHA256 (64 hex characters)
        self.assertEqual(len(hash1), 64)

    @unittest.skipIf(
        True,  # Skip by default to avoid ChromaDB dependency in fast tests
        "Requires ChromaDB and embedding model installation"
    )
    def test_upsert_and_retrieve(self):
        """Test document upsert and retrieval."""
        store = IndexStore(self.config)

        # Create test document
        doc = DigestDocument(
            doc_id="test:channel:1",
            source_type="telegram",
            source_id="test:channel",
            external_id="1",
            topic_ids=["test"],
            published_at=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            url="https://t.me/test/1",
            author_label="Test Channel",
            language="en",
            content_kind="post",
            content_hash=compute_content_hash("Test content"),
            content="Test content"
        )

        # Upsert document
        stats = store.upsert_documents([doc])
        self.assertEqual(stats['added'], 1)
        self.assertEqual(stats['updated'], 0)
        self.assertEqual(stats['skipped'], 0)

        # Retrieve document
        retrieved = store.get_document(doc.doc_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.doc_id, doc.doc_id)
        self.assertEqual(retrieved.content, doc.content)

    @unittest.skipIf(
        True,
        "Requires ChromaDB and embedding model installation"
    )
    def test_idempotent_upsert(self):
        """Test that upserting same document doesn't create duplicates."""
        store = IndexStore(self.config)

        doc = DigestDocument(
            doc_id="test:channel:1",
            source_type="telegram",
            source_id="test:channel",
            external_id="1",
            topic_ids=["test"],
            published_at=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            url="https://t.me/test/1",
            author_label="Test Channel",
            language="en",
            content_kind="post",
            content_hash=compute_content_hash("Test content"),
            content="Test content"
        )

        # First upsert
        stats1 = store.upsert_documents([doc])
        self.assertEqual(stats1['added'], 1)

        # Second upsert with same content
        stats2 = store.upsert_documents([doc])
        self.assertEqual(stats2['skipped'], 1)

        # Upsert with modified content
        doc.content = "Modified content"
        doc.content_hash = compute_content_hash(doc.content)
        stats3 = store.upsert_documents([doc])
        self.assertEqual(stats3['updated'], 1)

    @unittest.skipIf(
        True,
        "Requires ChromaDB and embedding model installation"
    )
    def test_search_with_topic_filter(self):
        """Test semantic search with topic filtering."""
        store = IndexStore(self.config)

        # Create documents with different topics
        doc1 = DigestDocument(
            doc_id="test:channel:1",
            source_type="telegram",
            source_id="test:channel",
            external_id="1",
            topic_ids=["test"],
            published_at=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            url="https://t.me/test/1",
            author_label="Test Channel",
            language="en",
            content_kind="post",
            content_hash=compute_content_hash("Stock market analysis"),
            content="Stock market analysis"
        )

        doc2 = DigestDocument(
            doc_id="test:channel:2",
            source_type="telegram",
            source_id="test:channel",
            external_id="2",
            topic_ids=["other"],
            published_at=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            url="https://t.me/test/2",
            author_label="Test Channel",
            language="en",
            content_kind="post",
            content_hash=compute_content_hash("Weather forecast"),
            content="Weather forecast"
        )

        store.upsert_documents([doc1, doc2])

        # Search with topic filter
        results = store.search("market", topic_id="test", k=5)

        # Should only return documents from "test" topic
        self.assertTrue(all(r.metadata['topic_ids'] == 'test' for r in results))

    @unittest.skipIf(
        True,
        "Requires ChromaDB and embedding model installation"
    )
    def test_delete_by_doc_id(self):
        """Test document deletion by doc_id."""
        store = IndexStore(self.config)

        doc = DigestDocument(
            doc_id="test:channel:1",
            source_type="telegram",
            source_id="test:channel",
            external_id="1",
            topic_ids=["test"],
            published_at=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            url="https://t.me/test/1",
            author_label="Test Channel",
            language="en",
            content_kind="post",
            content_hash=compute_content_hash("Test content"),
            content="Test content"
        )

        store.upsert_documents([doc])

        # Delete document
        deleted = store.delete_by_doc_id(doc.doc_id)
        self.assertTrue(deleted)

        # Verify deletion
        retrieved = store.get_document(doc.doc_id)
        self.assertIsNone(retrieved)


if __name__ == "__main__":
    unittest.main()
