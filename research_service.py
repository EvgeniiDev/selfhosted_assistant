from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from capability_registry import CapabilityRegistry, CapabilitySpec
from llm_core import LLMGateway
from logger import calendar_logger
from research_context_store import ResearchContextStore
from skill_execution_service import SkillExecutionService, SkillExecutionSpec


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

    def __init__(
        self,
        gateway: LLMGateway,
        context_store: ResearchContextStore | None = None,
        capability_registry: CapabilityRegistry | None = None,
    ):
        self.gateway = gateway
        self.context_store = context_store or ResearchContextStore()
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.capability_spec = self.capability_registry.get("research")
        self.skill_service = SkillExecutionService(
            gateway=self.gateway,
            spec=self._build_skill_spec(self.capability_spec),
        )

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

        if self.context_store.is_clarification_pending(chat_id):
            return True

        return False

    def cancel_clarification(self, chat_id: str) -> bool:
        return self.context_store.cancel_clarification(chat_id)

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

        response = self.skill_service.execute(
            user_text=user_text,
            mode=mode,
            context_payload=self._build_skill_context(existing_context),
            metadata={
                "is_private": True,
                "handler": "ResearchMode",
                "copilot_session_id": copilot_session_id,
            },
        )
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


    def _build_skill_context(self, context_payload: dict[str, Any]) -> dict[str, Any]:
        if not context_payload:
            return {}

        policy = self.capability_spec.context_policy
        findings_payload = []
        if policy.include_findings:
            for item in (context_payload.get("findings") or [])[:policy.max_findings]:
                claim = str(item.get("claim", "")).strip()
                status = str(item.get("status", "UNCERTAIN")).strip().upper()
                if claim:
                    findings_payload.append({"status": status, "claim": claim})

        source_payload = []
        if policy.include_sources:
            for item in (context_payload.get("sources") or [])[:policy.max_sources]:
                url = str(item.get("url", "")).strip()
                if url:
                    source_payload.append(url)

        serialized_context: dict[str, Any] = {}
        if policy.include_brief:
            serialized_context["brief"] = str(context_payload.get("brief", "")).strip()
        if policy.include_findings:
            serialized_context["findings"] = findings_payload
        if policy.include_sources:
            serialized_context["sources"] = source_payload
        return serialized_context

    def _build_skill_spec(self, capability_spec: CapabilitySpec) -> SkillExecutionSpec:
        return SkillExecutionSpec(
            skill_name=capability_spec.skill_name,
            task_type=capability_spec.task_type,
            system_prompt=capability_spec.system_prompt,
            mcp_server=capability_spec.mcp_server,
            text_only=capability_spec.text_only,
            allow_mcp_tools=capability_spec.allow_mcp_tools,
        )

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