"""Smoke check for research skill flow via Copilot provider.

Usage:
    .venv/Scripts/python.exe scripts/smoke_research_skill.py --prompt "Исследуй тему edge ai chips"
"""

from __future__ import annotations

import argparse
import json
import re
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
    parser = argparse.ArgumentParser(description="Run a smoke research request against Copilot provider")
    parser.add_argument("--prompt", default="Исследуй тему AI agents for software testing")
    parser.add_argument("--model", default="gpt-4.1")
    args = parser.parse_args()

    provider = CopilotSDKProvider()
    wrapped_prompt = (
        "Используй skill `research-pipeline` из подключенных skills.\n"
        f"Тема: {args.prompt}\n\n"
        "Не задавай уточняющих вопросов. Если контекст неполный, сделай разумные допущения и продолжай.\n"
        "Требования к ответу:\n"
        "1) Краткий итог (3-7 пунктов)\n"
        "2) Факты с метками [CONFIRMED]/[UNCERTAIN]/[NOT_FOUND]\n"
        "3) Список источников (URL)\n"
        "4) Что осталось непроверенным\n"
        "5) Включи минимум один http(s) URL\n"
    )

    request = LLMRequest(
        content=wrapped_prompt,
        task_type="research",
        system_prompt="You are a concise research assistant.",
        text_only=True,
        allow_mcp_tools=True,
    )

    try:
        response = provider.generate(request=request, model_id=args.model)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    text = (response.content or "").strip()
    has_url = bool(re.search(r"https?://", text))
    ok = bool(text) and has_url

    print(
        json.dumps(
            {
                "ok": ok,
                "provider": response.provider,
                "model": response.model_id,
                "has_url": has_url,
                "preview": text[:250],
            },
            ensure_ascii=False,
        )
    )

    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
