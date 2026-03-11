from __future__ import annotations

import json
from typing import Any

from capability_registry import CapabilityRegistry, CapabilitySpec
from llm_core import LLMGateway
from logger import calendar_logger
from models import CalendarEvent
from skill_execution_service import SkillExecutionService, SkillExecutionSpec


class CalendarEventSkillService:
    """Skill-backed calendar event extractor that returns the existing CalendarEvent model."""

    def __init__(
        self,
        gateway: LLMGateway,
        capability_registry: CapabilityRegistry | None = None,
    ) -> None:
        self.gateway = gateway
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.capability_spec = self.capability_registry.get("calendar_event")
        self.skill_service = SkillExecutionService(
            gateway=self.gateway,
            spec=self._build_skill_spec(self.capability_spec),
        )

    def create_calendar_event(self, user_message: str, current_time_text: str) -> CalendarEvent | None:
        response = self.skill_service.execute(
            user_text=user_message,
            mode="new",
            context_payload={
                "current_local_datetime": current_time_text,
            },
            metadata={
                "is_private": False,
                "handler": "CalendarEventSkillService",
            },
        )
        content = (response.content or "").strip()
        if not content:
            return None
        return self._parse_calendar_event(content)

    def _parse_calendar_event(self, response_content: str) -> CalendarEvent | None:
        parsed = self._extract_json(response_content)
        if not parsed or parsed.get("type") != "calendar_event":
            return None

        data = parsed.get("data") or {}
        try:
            return CalendarEvent(**data)
        except Exception as exc:
            calendar_logger.log_error(exc, "calendar_event_skill_service._parse_calendar_event")
            return None

    def _extract_json(self, content: str) -> dict[str, Any] | None:
        try:
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start < 0 or json_end <= json_start:
                return None
            return json.loads(content[json_start:json_end])
        except json.JSONDecodeError as exc:
            calendar_logger.log_error(exc, "calendar_event_skill_service._extract_json")
            return None

    def _build_skill_spec(self, capability_spec: CapabilitySpec) -> SkillExecutionSpec:
        return SkillExecutionSpec(
            skill_name=capability_spec.skill_name,
            task_type=capability_spec.task_type,
            system_prompt=capability_spec.system_prompt,
            mcp_server=capability_spec.mcp_server,
            text_only=capability_spec.text_only,
            allow_mcp_tools=capability_spec.allow_mcp_tools,
        )