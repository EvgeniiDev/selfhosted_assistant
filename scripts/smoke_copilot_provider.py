"""Smoke check for Copilot provider adapter.

Usage:
    .venv/Scripts/python.exe scripts/smoke_copilot_provider.py --prompt "hello"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()

from integrations.copilot_sdk import CopilotSDKProvider
from llm_core import LLMRequest


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a smoke request against Copilot provider")
    parser.add_argument("--prompt", default="Reply with exactly: smoke-ok")
    parser.add_argument("--model", default="gpt-4.1")
    args = parser.parse_args()

    provider = CopilotSDKProvider()
    request = LLMRequest(
        content=args.prompt,
        task_type="unknown",
        system_prompt="You are a concise assistant.",
        text_only=True,
        allow_mcp_tools=False,
    )

    try:
        response = provider.generate(request=request, model_id=args.model)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "ok": bool(response.content.strip()),
                "provider": response.provider,
                "model": response.model_id,
                "usage": response.usage,
                "preview": response.content[:120],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
