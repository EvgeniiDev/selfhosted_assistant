from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from llm_core import LLMGateway, LLMRequest


@dataclass(slots=True)
class SkillExecutionSpec:
    skill_name: str
    task_type: str
    system_prompt: str = ""
    mcp_server: str = ""
    text_only: bool = True
    allow_mcp_tools: bool = False


class SkillExecutionService:
    """Thin host-side runtime for invoking connected Copilot skills.

    Product behavior should live in the skill itself. This service is only
    responsible for packaging host context and forwarding the request through
    the LLM gateway.
    """

    def __init__(self, gateway: LLMGateway, spec: SkillExecutionSpec) -> None:
        self.gateway = gateway
        self.spec = spec

    def execute(
        self,
        user_text: str,
        mode: str = "new",
        context_payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        request = self._build_request(
            user_text=user_text,
            mode=mode,
            context_payload=context_payload or {},
            metadata=metadata or {},
        )
        return self.gateway.generate(request)

    def _build_request(
        self,
        user_text: str,
        mode: str,
        context_payload: dict[str, Any],
        metadata: dict[str, Any],
    ) -> LLMRequest:
        request_metadata = dict(metadata)
        request_metadata["skill_name"] = self.spec.skill_name
        if self.spec.mcp_server:
            request_metadata.setdefault("mcp_server", self.spec.mcp_server)

        return LLMRequest(
            content=self._build_prompt(user_text, mode, context_payload),
            task_type=self.spec.task_type,
            system_prompt=self.spec.system_prompt,
            metadata=request_metadata,
            text_only=self.spec.text_only,
            allow_mcp_tools=self.spec.allow_mcp_tools,
        )

    def _build_prompt(self, user_text: str, mode: str, context_payload: dict[str, Any]) -> str:
        skill_name = self.spec.skill_name
        normalized_mode = (mode or "new").strip().lower() or "new"
        lines = [
            f"Use skill `{skill_name}` from the connected skills as the source of truth.",
            "Host runtime context:",
            f"- skill: {skill_name}",
            f"- mode: {normalized_mode}",
            f"- user_request: {user_text}",
        ]

        if context_payload:
            serialized_context = json.dumps(context_payload, ensure_ascii=False, indent=2)
            lines.extend(
                [
                    "- host_context_available: yes",
                    "Host context JSON:",
                    serialized_context,
                ]
            )
        else:
            lines.append("- host_context_available: no")

        lines.extend(
            [
                "Host requirements:",
                "- Follow the selected skill's workflow and output contract.",
                "- Use the provided mode and host context when relevant.",
                "- Return a user-facing answer only.",
            ]
        )
        return "\n".join(lines)