"""
IndexStore: ChromaDB wrapper for document indexing and retrieval.
"""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings
from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.core.schema import Document as LlamaDocument, TextNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from digest.models import DigestDocument, SearchResult, DigestConfig


class IndexStore:
    """
    Vector index store backed by ChromaDB.

    Provides idempotent upsert, semantic search, and metadata filtering.
    """

    def __init__(self, config: DigestConfig):
        """
        Initialize index store with ChromaDB and embedding model.

        Args:
            config: Digest configuration
        """
        self.config = config
        self.chroma_path = Path(config.chroma_path)
        self.chroma_path.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB client
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.chroma_path),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

        # Get or create collection
        self.collection_name = "digest_documents"
        try:
            self.chroma_collection = self.chroma_client.get_collection(
                name=self.collection_name
            )
        except Exception:
            self.chroma_collection = self.chroma_client.create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )

        # Initialize embedding model
        self.embed_model = HuggingFaceEmbedding(
            model_name=config.embedding_model,
            cache_folder=str(self.chroma_path / "embeddings_cache")
        )

        # Initialize vector store
        self.vector_store = ChromaVectorStore(chroma_collection=self.chroma_collection)
        self.storage_context = StorageContext.from_defaults(vector_store=self.vector_store)

        # Initialize or load index
        try:
            self.index = VectorStoreIndex.from_vector_store(
                self.vector_store,
                embed_model=self.embed_model
            )
        except Exception:
            self.index = VectorStoreIndex.from_documents(
                [],
                storage_context=self.storage_context,
                embed_model=self.embed_model
            )

    def upsert_documents(self, documents: list[DigestDocument]) -> dict:
        """
        Upsert documents into the index (idempotent).

        If a document with the same doc_id exists, it will be updated.
        Deduplication is handled via content_hash.

        Args:
            documents: List of DigestDocument objects to upsert

        Returns:
            Dictionary with stats: {'added': int, 'updated': int, 'skipped': int}
        """
        stats = {'added': 0, 'updated': 0, 'skipped': 0}

        for doc in documents:
            # Check if document already exists by doc_id
            existing = self._get_by_doc_id(doc.doc_id)

            if existing:
                # Check if content has changed via content_hash
                existing_hash = existing.get('content_hash')
                if existing_hash == doc.content_hash:
                    stats['skipped'] += 1
                    continue
                else:
                    # Content changed, delete old version
                    self._delete_by_doc_id(doc.doc_id)
                    stats['updated'] += 1
            else:
                stats['added'] += 1

            # Create TextNode for indexing
            node = TextNode(
                text=doc.content,
                id_=doc.doc_id,
                metadata={
                    'doc_id': doc.doc_id,
                    'source_type': doc.source_type,
                    'source_id': doc.source_id,
                    'external_id': doc.external_id,
                    'topic_ids': ','.join(doc.topic_ids),  # Store as comma-separated
                    'published_at': doc.published_at.isoformat(),
                    'ingested_at': doc.ingested_at.isoformat(),
                    'url': doc.url,
                    'author_label': doc.author_label,
                    'language': doc.language,
                    'content_kind': doc.content_kind,
                    'content_hash': doc.content_hash,
                    'chunk_id': doc.chunk_id or '',
                    'parent_doc_id': doc.parent_doc_id or ''
                }
            )

            # Insert into index
            self.index.insert_nodes([node])

        return stats

    def search(
        self,
        query: str,
        topic_id: Optional[str] = None,
        k: int = 8,
        filters: Optional[dict] = None
    ) -> list[SearchResult]:
        """
        Semantic search over indexed documents.

        Args:
            query: Search query text
            topic_id: Optional topic filter
            k: Number of results to return
            filters: Additional metadata filters (e.g., {'source_id': 'telegram:Channel1'})

        Returns:
            List of SearchResult objects
        """
        # Build metadata filters
        metadata_filters = {}
        if filters:
            metadata_filters.update(filters)

        # Add topic filter if specified
        # Note: We need to check if topic_id is in the comma-separated list
        # ChromaDB doesn't have native list filtering, so we'll filter post-retrieval

        # Perform retrieval
        retriever = self.index.as_retriever(
            similarity_top_k=k * 2 if topic_id else k  # Over-fetch if we need to filter by topic
        )

        try:
            nodes = retriever.retrieve(query)
        except Exception:
            # If index is empty, return empty results
            return []

        # Convert to SearchResult and apply topic filtering
        results = []
        for node in nodes:
            metadata = node.node.metadata

            # Apply topic filter if specified
            if topic_id:
                doc_topics = metadata.get('topic_ids', '').split(',')
                if topic_id not in doc_topics:
                    continue

            # Apply additional metadata filters
            if filters:
                match = all(
                    metadata.get(k) == v
                    for k, v in filters.items()
                )
                if not match:
                    continue

            results.append(SearchResult(
                doc_id=metadata['doc_id'],
                content=node.node.text,
                source_id=metadata['source_id'],
                published_at=datetime.fromisoformat(metadata['published_at']),
                url=metadata['url'],
                score=node.score,
                metadata=metadata
            ))

            if len(results) >= k:
                break

        return results

    def delete_by_doc_id(self, doc_id: str) -> bool:
        """
        Delete document by doc_id.

        Args:
            doc_id: Document ID to delete

        Returns:
            True if document was deleted, False if not found
        """
        return self._delete_by_doc_id(doc_id)

    def delete_by_source(self, source_id: str) -> int:
        """
        Delete all documents from a specific source.

        Args:
            source_id: Source ID (e.g., 'telegram:Channel1')

        Returns:
            Number of documents deleted
        """
        # This is a simplified implementation
        # In production, you might want to use ChromaDB's delete with where clause
        deleted = 0

        try:
            # Get all doc_ids for this source
            results = self.chroma_collection.get(
                where={"source_id": source_id}
            )

            if results and results.get('ids'):
                for doc_id in results['ids']:
                    if self._delete_by_doc_id(doc_id):
                        deleted += 1
        except Exception:
            pass

        return deleted

    def get_document(self, doc_id: str) -> Optional[DigestDocument]:
        """
        Retrieve a document by doc_id.

        Args:
            doc_id: Document ID

        Returns:
            DigestDocument if found, None otherwise
        """
        doc_data = self._get_by_doc_id(doc_id)
        if not doc_data:
            return None

        metadata = doc_data.get('metadata', {})

        return DigestDocument(
            doc_id=metadata['doc_id'],
            source_type=metadata['source_type'],
            source_id=metadata['source_id'],
            external_id=metadata['external_id'],
            topic_ids=metadata['topic_ids'].split(','),
            published_at=datetime.fromisoformat(metadata['published_at']),
            ingested_at=datetime.fromisoformat(metadata['ingested_at']),
            url=metadata['url'],
            author_label=metadata['author_label'],
            language=metadata['language'],
            content_kind=metadata['content_kind'],
            content_hash=metadata['content_hash'],
            content=doc_data['content'],
            chunk_id=metadata.get('chunk_id') or None,
            parent_doc_id=metadata.get('parent_doc_id') or None
        )

    def _get_by_doc_id(self, doc_id: str) -> Optional[dict]:
        """Get document data by doc_id from ChromaDB."""
        try:
            results = self.chroma_collection.get(
                ids=[doc_id],
                include=['metadatas', 'documents']
            )

            if results and results.get('ids') and len(results['ids']) > 0:
                return {
                    'content': results['documents'][0],
                    'metadata': results['metadatas'][0],
                    **results['metadatas'][0]
                }
        except Exception:
            pass

        return None

    def _delete_by_doc_id(self, doc_id: str) -> bool:
        """Delete document by doc_id from ChromaDB."""
        try:
            self.chroma_collection.delete(ids=[doc_id])
            return True
        except Exception:
            return False


def compute_content_hash(content: str) -> str:
    """
    Compute SHA256 hash of content for deduplication.

    Args:
        content: Text content

    Returns:
        SHA256 hash as hex string
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()
