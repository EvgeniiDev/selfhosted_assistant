"""
Digest skill service for Q&A over indexed content.
"""

from typing import Optional

from llm_core.contracts import LLMGateway
from capability_registry import CapabilityRegistry

from digest.config import load_config
from digest.index_store import IndexStore
from digest.retrieval_service import RetrievalService
from digest.qa_handler import QAHandler
from digest.models import QAResponse


class DigestSkillService:
    """
    Digest Q&A service integrated with the bot.

    Handles user questions about indexed content (Telegram channels, YouTube, etc.)
    """

    _instance = None

    def __init__(
        self,
        gateway: LLMGateway,
        capability_registry: Optional[CapabilityRegistry] = None
    ):
        """
        Initialize digest skill service.

        Args:
            gateway: LLM gateway for answer generation
            capability_registry: Optional capability registry
        """
        self.gateway = gateway
        self.capability_registry = capability_registry or CapabilityRegistry()

        # Load digest configuration
        try:
            self.digest_config = load_config()
        except Exception as e:
            print(f"[warn] Could not load digest config: {e}")
            self.digest_config = None
            self._initialized = False
            return

        # Initialize index store
        try:
            self.index_store = IndexStore(self.digest_config)
        except Exception as e:
            print(f"[warn] Could not initialize index store: {e}")
            self.index_store = None
            self._initialized = False
            return

        # Initialize retrieval service
        self.retrieval_service = RetrievalService(
            index_store=self.index_store,
            config=self.digest_config
        )

        # Initialize QA handler
        self.qa_handler = QAHandler(
            retrieval_service=self.retrieval_service,
            gateway=self.gateway
        )

        self._initialized = True

    @classmethod
    def get_instance(
        cls,
        gateway: LLMGateway,
        capability_registry: Optional[CapabilityRegistry] = None
    ) -> "DigestSkillService":
        """
        Get or create singleton instance.

        Args:
            gateway: LLM gateway
            capability_registry: Optional capability registry

        Returns:
            DigestSkillService instance
        """
        if cls._instance is None:
            cls._instance = cls(gateway, capability_registry)

        return cls._instance

    def answer_question(self, user_message: str) -> Optional[QAResponse]:
        """
        Answer a user's question using the digest knowledge base.

        Args:
            user_message: User's question

        Returns:
            QAResponse if successful, None if service not initialized
        """
        if not self._initialized:
            print("[warn] Digest service not initialized")
            return None

        try:
            return self.qa_handler.answer_question(user_message)
        except Exception as e:
            print(f"[error] Error answering digest question: {e}")
            return None

    def format_response(self, qa_response: QAResponse) -> str:
        """
        Format QA response for Telegram.

        Args:
            qa_response: QA response object

        Returns:
            Formatted text for Telegram
        """
        parts = []

        # Add answer
        parts.append(qa_response.answer)

        # Add evidence if available
        if qa_response.evidence:
            parts.append("\n\n📚 Источники:")
            for idx, evidence in enumerate(qa_response.evidence[:5], 1):
                date_str = evidence.published_at.strftime('%d.%m.%Y')
                parts.append(
                    f"{idx}. {evidence.source_label} ({date_str})"
                )

        # Add confidence if low
        if qa_response.confidence < 0.5:
            parts.append(f"\n\n⚠️ Уверенность: {qa_response.confidence:.0%}")

        return "\n".join(parts)

    def is_initialized(self) -> bool:
        """Check if service is properly initialized."""
        return self._initialized
