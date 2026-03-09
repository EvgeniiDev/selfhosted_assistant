from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_core import LLMGateway, LLMRequest
from logger import calendar_logger
from research_context_store import ResearchContextStore


@dataclass(slots=True)
class ResearchExecutionResult:
    mode: str
    full_response: str
    outbound_text: str
    sources: list[str]


class ResearchService:
    """Application-layer orchestration for research requests.

    This service keeps Telegram-specific transport details out of the research flow,
    which makes the core behavior easy to exercise in integration tests.
    """

    def __init__(self, gateway: LLMGateway, context_store: ResearchContextStore | None = None):
        self.gateway = gateway
        self.context_store = context_store or ResearchContextStore()

    def reset_chat(self, chat_id: str) -> bool:
        return self.context_store.reset_chat(chat_id)

    def list_sources(self, chat_id: str) -> list[str]:
        return self.context_store.list_sources(chat_id)

    def get_active_context(self, chat_id: str) -> dict[str, Any] | None:
        return self.context_store.get_active_context(chat_id)

    def should_start_new(self, chat_id: str, user_text: str) -> bool:
        if not self._is_research_start(user_text):
            return False
        return bool(chat_id)

    def should_followup(self, chat_id: str, user_text: str) -> bool:
        if not chat_id:
            return False

        context = self.context_store.get_active_context(chat_id)
        if not context:
            return False

        if self._is_research_followup(user_text):
            return True

        if self.context_store.is_clarification_pending(chat_id) and self._looks_like_research_clarification(user_text):
            return True

        return False

    def resolve_mode(self, chat_id: str, user_text: str, mode_hint: str | None = None) -> str:
        existing_context = self.context_store.get_active_context(chat_id) or {}
        mode = (mode_hint or "new").strip().lower() or "new"

        if self._is_research_followup(user_text) and existing_context:
            mode = "followup"
        if mode == "followup" and not existing_context:
            mode = "new"
        return mode

    def execute(self, chat_id: str, user_text: str, mode_hint: str | None = None) -> ResearchExecutionResult:
        existing_context = self.context_store.get_active_context(chat_id) or {}
        mode = self.resolve_mode(chat_id, user_text, mode_hint)
        copilot_session_id = self.context_store.get_or_create_copilot_session_id(chat_id) if chat_id else ""

        request = LLMRequest(
            content=self._build_prompt(user_text, mode, existing_context),
            task_type="research",
            system_prompt="You are a precise research assistant. Follow the requested output structure exactly.",
            metadata={
                "is_private": True,
                "handler": "ResearchMode",
                "copilot_session_id": copilot_session_id,
            },
            text_only=True,
            allow_mcp_tools=True,
        )

        response = self.gateway.generate(request)
        response_text = (response.content or "").strip()
        if not response_text:
            raise RuntimeError("empty response")

        try:
            self.context_store.save_turn(chat_id, user_text, response_text)
            self.context_store.save_artifacts(chat_id, response_text)
        except Exception as exc:
            calendar_logger.log_error(exc, "research_service.execute.store")

        compact_answer = self._compact_answer(response_text)
        prefix = "🔎 Follow-up исследование" if mode == "followup" else "🔎 Исследование"
        return ResearchExecutionResult(
            mode=mode,
            full_response=response_text,
            outbound_text=f"{prefix}\n\n{compact_answer}",
            sources=self.context_store.list_sources(chat_id),
        )

    def _build_prompt(self, user_text: str, mode: str, context_payload: dict[str, Any]) -> str:
        if mode == "followup":
            brief = (context_payload.get("brief") or "").strip()
            findings = context_payload.get("findings") or []
            sources = context_payload.get("sources") or []

            top_findings: list[str] = []
            for item in findings[:10]:
                claim = str(item.get("claim", "")).strip()
                status = str(item.get("status", "UNCERTAIN")).strip().upper()
                if claim:
                    top_findings.append(f"- [{status}] {claim}")

            top_sources: list[str] = []
            for item in sources[:10]:
                url = str(item.get("url", "")).strip()
                if url:
                    top_sources.append(f"- {url}")

            return (
                "Используй skill `research-pipeline`.\n"
                "Это follow-up к предыдущему исследованию.\n\n"
                f"Вопрос пользователя: {user_text}\n"
                "Контекст предыдущего исследования:\n"
                f"- Краткий итог: {brief or 'нет данных'}\n"
                f"- Ключевые факты:\n{chr(10).join(top_findings) if top_findings else '- нет данных'}\n"
                f"- Источники:\n{chr(10).join(top_sources) if top_sources else '- нет данных'}\n\n"
                "Требования:\n"
                "1) Ответь по существующему контексту\n"
                "2) Если данных мало, добери только недостающее\n"
                "3) Отметь новые данные и новые источники отдельно\n"
            )

        return (
            "Используй skill `research-pipeline` из подключенных skills.\n"
            f"Тема: {user_text}\n\n"
            "Требования к ответу:\n"
            "1) Краткий итог (3-7 пунктов)\n"
            "2) Факты с метками [CONFIRMED]/[UNCERTAIN]/[NOT_FOUND]\n"
            "3) Список источников (URL)\n"
            "4) Что осталось непроверенным\n"
        )

    def _compact_answer(self, response_text: str) -> str:
        text = (response_text or "").strip()
        if not text:
            return "⚠️ Исследование завершилось пустым ответом."

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        compact_lines = lines[:18]
        compact = "\n".join(compact_lines)
        if len(lines) > len(compact_lines):
            compact += "\n\n...\nНапишите 'подробнее', чтобы углубиться по пунктам."

        if len(compact) > 2500:
            compact = compact[:2500].rstrip() + "\n\n...\nНапишите 'подробнее' для продолжения."
        return compact

    def _is_research_followup(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False

        followup_hints = (
            "подробнее",
            "раскрой",
            "уточни",
            "деталь",
            "разверни",
            "пункт",
            "follow-up",
            "follow up",
            "more details",
            "elaborate",
        )
        return any(hint in normalized for hint in followup_hints)

    def _is_research_start(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False

        start_hints = (
            "исследуй",
            "найди информацию",
            "проведи исследование",
            "изучи тему",
            "deep dive",
            "investigate",
            "research",
        )
        return any(hint in normalized for hint in start_hints)

    def _looks_like_research_clarification(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False

        clarification_markers = (
            "меня интерес",
            "горизонт",
            "частичн",
            "полная замена",
            "в 3 года",
            "в 5 лет",
            "в 10 лет",
            "важна",
            "важно",
            "фокус",
            "сфокусируй",
        )
        return any(marker in normalized for marker in clarification_markers)