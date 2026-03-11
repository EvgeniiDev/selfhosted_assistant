from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CapabilityContextPolicy:
    include_brief: bool = True
    include_findings: bool = True
    include_sources: bool = True
    max_findings: int = 10
    max_sources: int = 10


@dataclass(slots=True)
class CapabilitySpec:
    capability_id: str
    skill_name: str
    task_type: str
    system_prompt: str = ""
    mcp_server: str = ""
    text_only: bool = True
    allow_mcp_tools: bool = False
    context_policy: CapabilityContextPolicy = field(default_factory=CapabilityContextPolicy)


@dataclass(slots=True)
class IntentClassificationConfig:
    task_type: str = "classification"
    system_prompt: str = (
        "Classify the input text into exactly one category. Output only the category word."
    )
    valid_types: tuple[str, ...] = (
        "calendar_event",
        "task",
        "note",
        "research",
        "list_notes",
        "unknown",
    )
    default_intent: str = "note"
    heuristics: dict[str, tuple[str, ...]] = field(default_factory=dict)
    datetime_keywords: tuple[str, ...] = ()


class CapabilityRegistry:
    """Loads skill-capability bindings from JSON config."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = Path(config_path or self._default_config_path()).resolve()
        self._raw = self._load_json(self.config_path)
        self._capabilities = self._parse_capabilities(self._raw)
        self._intent_classification = self._parse_intent_classification(self._raw)

    def get(self, capability_id: str) -> CapabilitySpec:
        spec = self._capabilities.get(capability_id)
        if spec is None:
            raise KeyError(f"Unknown capability: {capability_id}")
        return spec

    def has(self, capability_id: str) -> bool:
        return capability_id in self._capabilities

    def get_intent_classification(self) -> IntentClassificationConfig:
        return self._intent_classification

    def _default_config_path(self) -> str:
        configured = os.getenv("CAPABILITY_REGISTRY_PATH", "capability_registry.json")
        return configured

    def _load_json(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _parse_capabilities(self, payload: dict[str, Any]) -> dict[str, CapabilitySpec]:
        capabilities = payload.get("capabilities") or {}
        parsed: dict[str, CapabilitySpec] = {}
        for capability_id, item in capabilities.items():
            if not isinstance(item, dict):
                continue

            context_policy_payload = item.get("context_policy") or {}
            context_policy = CapabilityContextPolicy(
                include_brief=bool(context_policy_payload.get("include_brief", True)),
                include_findings=bool(context_policy_payload.get("include_findings", True)),
                include_sources=bool(context_policy_payload.get("include_sources", True)),
                max_findings=max(0, int(context_policy_payload.get("max_findings", 10))),
                max_sources=max(0, int(context_policy_payload.get("max_sources", 10))),
            )

            parsed[capability_id] = CapabilitySpec(
                capability_id=capability_id,
                skill_name=str(item.get("skill_name", "")).strip(),
                task_type=str(item.get("task_type", capability_id)).strip() or capability_id,
                system_prompt=str(item.get("system_prompt", "")),
                mcp_server=str(item.get("mcp_server", "")).strip(),
                text_only=bool(item.get("text_only", True)),
                allow_mcp_tools=bool(item.get("allow_mcp_tools", False)),
                context_policy=context_policy,
            )

        return parsed

    def _parse_intent_classification(self, payload: dict[str, Any]) -> IntentClassificationConfig:
        item = payload.get("classification") or {}
        heuristics_payload = item.get("heuristics") or {}
        heuristics: dict[str, tuple[str, ...]] = {}
        for intent_name, keywords in heuristics_payload.items():
            if isinstance(keywords, list):
                heuristics[intent_name] = tuple(str(keyword).lower() for keyword in keywords if str(keyword).strip())

        valid_types_payload = item.get("valid_types") or IntentClassificationConfig.valid_types
        valid_types = tuple(str(value).strip() for value in valid_types_payload if str(value).strip())
        if not valid_types:
            valid_types = IntentClassificationConfig.valid_types

        datetime_keywords_payload = item.get("datetime_keywords") or []

        return IntentClassificationConfig(
            task_type=str(item.get("task_type", "classification")).strip() or "classification",
            system_prompt=str(item.get("system_prompt", IntentClassificationConfig.system_prompt)),
            valid_types=valid_types,
            default_intent=str(item.get("default_intent", "note")).strip() or "note",
            heuristics=heuristics,
            datetime_keywords=tuple(
                str(keyword).lower() for keyword in datetime_keywords_payload if str(keyword).strip()
            ),
        )