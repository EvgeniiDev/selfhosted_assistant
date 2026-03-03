"""Policy enforcement utilities for LLM gateway/provider interactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_core.contracts import LLMRequest


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    code: str
    reason: str
    details: dict[str, Any]


class TextOnlyPolicyGuard:
    """Deny risky tool-oriented instructions when text-only mode is enabled."""

    _DENY_PATTERNS = (
        "edit file",
        "write file",
        "delete file",
        "run shell",
        "execute command",
        "terminal command",
        "rm -rf",
        "git reset --hard",
        "powershell",
        "bash -c",
    )

    def evaluate(self, request: LLMRequest, allowed_mcp_servers: list[str]) -> PolicyDecision:
        if not request.text_only:
            return PolicyDecision(
                allowed=True,
                code="policy_not_text_only",
                reason="Text-only restrictions are disabled for this request.",
                details={"allow_mcp_tools": request.allow_mcp_tools},
            )

        lowered = request.content.lower()
        denied_pattern = next((item for item in self._DENY_PATTERNS if item in lowered), None)
        if denied_pattern:
            return PolicyDecision(
                allowed=False,
                code="text_only_denied_tool_intent",
                reason="The request asks for a prohibited write/shell style action.",
                details={"matched_pattern": denied_pattern},
            )

        if request.allow_mcp_tools:
            requested_server = str(request.metadata.get("mcp_server", "")).strip()
            if requested_server and requested_server not in allowed_mcp_servers:
                return PolicyDecision(
                    allowed=False,
                    code="mcp_server_not_whitelisted",
                    reason="Requested MCP server is not in whitelist.",
                    details={"mcp_server": requested_server},
                )

        return PolicyDecision(
            allowed=True,
            code="policy_allowed",
            reason="Request passed text-only and MCP whitelist checks.",
            details={"allow_mcp_tools": request.allow_mcp_tools},
        )
