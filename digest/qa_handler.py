"""
Q&A handler for answering questions over indexed content.
"""

from typing import Optional

from llm_core.contracts import LLMGateway, LLMRequest

from digest.retrieval_service import RetrievalService
from digest.models import QAResponse, EvidenceSnippet, RetrievalResult


class QAHandler:
    """
    Q&A orchestration over digest knowledge base.

    Handles:
    - Topic detection
    - Evidence retrieval from multiple windows (recent + historical)
    - Answer generation with source attribution
    """

    def __init__(self, retrieval_service: RetrievalService, gateway: Optional[LLMGateway] = None):
        """
        Initialize QA handler.

        Args:
            retrieval_service: Retrieval service for searching content
            gateway: LLM gateway for answer generation (optional)
        """
        self.retrieval_service = retrieval_service
        self.gateway = gateway

    def answer_question(
        self,
        question: str,
        topic_id: Optional[str] = None
    ) -> QAResponse:
        """
        Answer a user question using indexed content.

        Args:
            question: User's question
            topic_id: Topic context (if known)

        Returns:
            QAResponse with answer and evidence
        """
        # Detect topic if not provided
        if topic_id is None:
            topic_id = self._detect_topic(question)

        if topic_id is None:
            return QAResponse(
                answer="Пожалуйста, уточните тему вопроса.",
                evidence=[],
                sources=[],
                confidence=0.0,
                needs_clarification=True,
                suggested_topics=list(self.retrieval_service.config.topics.keys())
            )

        # Retrieve evidence from multiple windows
        recent_results = self.retrieval_service.semantic_search(
            query=question,
            topic_id=topic_id,
            k=5,
            days=3  # Recent window
        )

        historical_results = self.retrieval_service.semantic_search(
            query=question,
            topic_id=topic_id,
            k=5,
            days=60  # Historical context
        )

        # Combine and deduplicate
        all_results = self._deduplicate_results(recent_results + historical_results)

        if not all_results:
            return QAResponse(
                answer=f"Недостаточно данных для ответа на вопрос по теме '{topic_id}'.",
                evidence=[],
                sources=[],
                confidence=0.0,
                needs_clarification=False,
                suggested_topics=[]
            )

        # Convert to evidence snippets
        evidence_snippets = self._results_to_evidence(all_results[:8])

        # Generate answer
        answer_text = self._generate_answer(question, evidence_snippets)

        # Extract unique sources
        sources = list(set(snippet.url for snippet in evidence_snippets))

        # Calculate confidence
        confidence = min(len(evidence_snippets) / 5.0, 1.0)

        return QAResponse(
            answer=answer_text,
            evidence=evidence_snippets,
            sources=sources,
            confidence=confidence,
            needs_clarification=False,
            suggested_topics=[]
        )

    def _detect_topic(self, question: str) -> Optional[str]:
        """
        Detect topic from question.

        Args:
            question: User's question

        Returns:
            Topic ID or None
        """
        question_lower = question.lower()

        # Check query aliases for each topic
        for topic_id, topic_config in self.retrieval_service.config.topics.items():
            for alias in topic_config.query_aliases:
                if alias.lower() in question_lower:
                    return topic_id

        # Default to first topic if only one exists
        if len(self.retrieval_service.config.topics) == 1:
            return list(self.retrieval_service.config.topics.keys())[0]

        return None

    def _deduplicate_results(self, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Remove duplicate results based on content."""
        seen_content = set()
        unique_results = []

        for result in results:
            content_key = result.content[:100]  # Use prefix as key
            if content_key not in seen_content:
                seen_content.add(content_key)
                unique_results.append(result)

        return unique_results

    def _results_to_evidence(self, results: list[RetrievalResult]) -> list[EvidenceSnippet]:
        """Convert retrieval results to evidence snippets."""
        snippets = []

        for result in results:
            # Extract source label
            source_label = result.source_id.split(':')[-1]

            snippet = EvidenceSnippet(
                text=result.content,
                source_id=result.source_id,
                source_label=source_label,
                published_at=result.published_at,
                url=result.url,
                relevance_score=result.score
            )

            snippets.append(snippet)

        return snippets

    def _generate_answer(
        self,
        question: str,
        evidence: list[EvidenceSnippet]
    ) -> str:
        """
        Generate answer from question and evidence.

        Args:
            question: User's question
            evidence: Evidence snippets

        Returns:
            Answer text
        """
        if self.gateway is None:
            # Fallback: simple evidence concatenation
            return self._generate_simple_answer(question, evidence)

        # Build context from evidence
        context_parts = []
        for idx, snippet in enumerate(evidence[:5], 1):
            context_parts.append(
                f"[{idx}] {snippet.source_label} ({snippet.published_at.strftime('%Y-%m-%d')}): "
                f"{snippet.text[:300]}"
            )

        context = "\n\n".join(context_parts)

        # Generate answer using LLM
        prompt = f"""На основе следующих источников ответь на вопрос пользователя.

Источники:
{context}

Вопрос: {question}

Инструкции:
- Дай краткий, точный ответ на вопрос
- Укажи, какие источники подтверждают ответ
- Если мнения авторов расходятся, отметь это
- Если данных недостаточно, скажи об этом

Ответ:"""

        try:
            request = LLMRequest(
                user_prompt=prompt,
                task_type="digest",
                model_id="gpt-5.4"
            )

            response = self.gateway.generate(request)
            return response.content

        except Exception as e:
            print(f"Error generating answer with LLM: {e}")
            return self._generate_simple_answer(question, evidence)

    def _generate_simple_answer(
        self,
        question: str,
        evidence: list[EvidenceSnippet]
    ) -> str:
        """Generate simple answer without LLM."""
        answer_parts = [
            f"Найдено {len(evidence)} релевантных фрагментов:"
        ]

        for idx, snippet in enumerate(evidence[:3], 1):
            answer_parts.append(
                f"\n{idx}. {snippet.source_label}: {snippet.text[:200]}..."
            )

        return "\n".join(answer_parts)
