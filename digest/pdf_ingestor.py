"""
PDF file ingestor for the digest RAG system.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from llama_index.core.node_parser import SentenceSplitter

from digest.config import DigestConfig
from digest.index_store import IndexStore, compute_content_hash
from digest.models import DigestDocument

logger = logging.getLogger(__name__)


class PDFIngestor:
    """
    Ingestor for PDF files into the digest RAG system.

    Handles text extraction, chunking, and deduplication via content hash.
    """

    def __init__(self, config: DigestConfig, index_store: IndexStore):
        """
        Initialize PDF ingestor.

        Args:
            config: Digest configuration
            index_store: Index store for document storage
        """
        self.config = config
        self.index_store = index_store
        self.chunker = SentenceSplitter(chunk_size=500, chunk_overlap=50)

    def ingest(
        self,
        file_path: str,
        topic_ids: list[str],
        source_label: str,
        file_name: str,
    ) -> dict:
        """
        Ingest a PDF file into the index store.

        Args:
            file_path: Path to the PDF file on disk
            topic_ids: Topic IDs to associate with the document
            source_label: Display label for the source
            file_name: Original filename (used for source_id and display)

        Returns:
            Dictionary with stats: {added, updated, skipped, chunks, title}
        """
        import fitz  # PyMuPDF

        file_stem = Path(file_name).stem
        source_id = f"pdf:{file_stem}"
        ingested_at = datetime.now(timezone.utc)

        # Extract text from all pages
        with fitz.open(file_path) as pdf:
            pages_text = []
            for page in pdf:
                pages_text.append(page.get_text())
            full_text = "\n".join(pages_text).strip()

        if not full_text:
            logger.warning(f"No text extracted from PDF: {file_name}")
            return {"added": 0, "updated": 0, "skipped": 0, "chunks": 0, "title": file_name}

        content_hash = compute_content_hash(full_text)
        doc_id = f"pdf:{file_stem}:{content_hash[:12]}"

        base_doc = DigestDocument(
            doc_id=doc_id,
            source_type="pdf",
            source_id=source_id,
            external_id=doc_id,
            topic_ids=topic_ids,
            published_at=ingested_at,
            ingested_at=ingested_at,
            url="",
            author_label=source_label or file_name,
            language=self._detect_language(full_text),
            content_kind="document",
            content_hash=content_hash,
            content=full_text,
        )

        # Chunk if content is long
        if len(full_text) > 600:
            documents = self._chunk_document(base_doc)
        else:
            documents = [base_doc]

        upsert_stats = self.index_store.upsert_documents(documents)
        return {
            "added": upsert_stats["added"],
            "updated": upsert_stats["updated"],
            "skipped": upsert_stats["skipped"],
            "chunks": len(documents),
            "title": file_name,
        }

    def _chunk_document(self, doc: DigestDocument) -> list[DigestDocument]:
        """Chunk a long document into smaller pieces."""
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
                parent_doc_id=doc.doc_id,
            )
            chunk_docs.append(chunk_doc)

        return chunk_docs

    def _detect_language(self, text: str) -> str:
        """Detect language by Cyrillic character ratio."""
        if not text:
            return "en"
        cyrillic = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
        cyrillic_count = sum(1 for c in text if c in cyrillic)
        return "ru" if cyrillic_count / len(text) > 0.15 else "en"
