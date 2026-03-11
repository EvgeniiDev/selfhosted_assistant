from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from capability_registry import CapabilityRegistry, CapabilitySpec
from llm_core import LLMGateway
from logger import calendar_logger
from models import Note
from skill_execution_service import SkillExecutionService, SkillExecutionSpec


class NoteSkillService:
    """Skill-backed note formatter that preserves the existing Note model contract."""

    def __init__(
        self,
        gateway: LLMGateway,
        capability_registry: CapabilityRegistry | None = None,
    ) -> None:
        self.gateway = gateway
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.capability_spec = self.capability_registry.get("note")
        self.skill_service = SkillExecutionService(
            gateway=self.gateway,
            spec=self._build_skill_spec(self.capability_spec),
        )

    def create_note(self, user_message: str, current_time: datetime) -> Note | None:
        response = self.skill_service.execute(
            user_text=user_message,
            mode="new",
            context_payload={
                "current_local_datetime": current_time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            metadata={
                "is_private": False,
                "handler": "NoteSkillService",
            },
        )
        content = (response.content or "").strip()
        if not content:
            return None
        return self._parse_note(content)

    def _parse_note(self, response_content: str) -> Note | None:
        parsed = self._extract_json(response_content)
        if not parsed or parsed.get("type") != "note":
            return None

        data = parsed.get("data") or {}
        try:
            return Note(**data)
        except Exception as exc:
            calendar_logger.log_error(exc, "note_skill_service._parse_note")
            return None

    def _extract_json(self, content: str) -> dict[str, Any] | None:
        try:
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start < 0 or json_end <= json_start:
                return None
            return json.loads(content[json_start:json_end])
        except json.JSONDecodeError as exc:
            calendar_logger.log_error(exc, "note_skill_service._extract_json")
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