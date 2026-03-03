"""Provider-agnostic contracts for the LLM core layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


JsonDict = dict[str, Any]


@dataclass(slots=True)
class LLMRequest:
    """Normalized request payload passed from application layer to LLM core."""

    content: str
    task_type: str
    system_prompt: str = ""
    metadata: JsonDict = field(default_factory=dict)
    text_only: bool = True
    allow_mcp_tools: bool = False


@dataclass(slots=True)
class LLMResponse:
    """Normalized model response with observability metadata."""

    content: str
    provider: str
    model_id: str
    usage: JsonDict = field(default_factory=dict)
    trace: JsonDict = field(default_factory=dict)
    raw_meta: JsonDict = field(default_factory=dict)


class LLMProvider(Protocol):
    """Provider interface implemented by concrete integrations (Copilot/OpenRouter)."""

    name: str

    def generate(self, request: LLMRequest, model_id: str) -> LLMResponse:
        """Generate a model response for the given normalized request."""
