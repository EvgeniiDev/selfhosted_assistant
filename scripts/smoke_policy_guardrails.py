"""Negative/positive checks for text-only and MCP whitelist policy."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm_core import LLMRequest
from llm_core.policy import TextOnlyPolicyGuard


def main() -> int:
    guard = TextOnlyPolicyGuard()

    denied = guard.evaluate(
        request=LLMRequest(
            content="Please run shell command rm -rf /tmp/x",
            task_type="unknown",
            text_only=True,
            allow_mcp_tools=False,
        ),
        allowed_mcp_servers=["web-search"],
    )
    print("deny_case:", denied.allowed, denied.code)

    denied_mcp = guard.evaluate(
        request=LLMRequest(
            content="Research request",
            task_type="unknown",
            text_only=True,
            allow_mcp_tools=True,
            metadata={"mcp_server": "filesystem"},
        ),
        allowed_mcp_servers=["web-search"],
    )
    print("deny_mcp_case:", denied_mcp.allowed, denied_mcp.code)

    allowed = guard.evaluate(
        request=LLMRequest(
            content="Summarize this paragraph",
            task_type="unknown",
            text_only=True,
            allow_mcp_tools=True,
            metadata={"mcp_server": "web-search"},
        ),
        allowed_mcp_servers=["web-search"],
    )
    print("allow_case:", allowed.allowed, allowed.code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
