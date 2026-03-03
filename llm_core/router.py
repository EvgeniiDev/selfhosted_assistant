"""Routing configuration and provider selection for the LLM core layer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_core.contracts import LLMRequest


JsonDict = dict[str, Any]


@dataclass(slots=True)
class ProviderRoute:
    """Resolved provider/model tuple for a single request."""

    provider: str
    model_id: str
    reason: str


class LLMRouter:
    """Selects provider and model according to `llm_routing_config.json`."""

    def __init__(self, config_path: str = "llm_routing_config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()

    def _load_config(self) -> JsonDict:
        with self.config_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def get_active_provider(self) -> str:
        return str(self.config.get("active_provider", "copilot"))

    def get_policy_defaults(self) -> JsonDict:
        policies = self.config.get("policies", {})
        return {
            "text_only": bool(policies.get("text_only", True)),
            "allow_mcp_tools": bool(policies.get("allow_mcp_tools", False)),
        }

    def get_allowed_mcp_servers(self) -> list[str]:
        policies = self.config.get("policies", {})
        allowed = policies.get("allowed_mcp_servers", [])
        if not isinstance(allowed, list):
            return []
        return [str(item) for item in allowed if str(item).strip()]

    def get_standby_provider(self) -> str:
        return str(self.config.get("standby_provider", "")).strip()

    def select_model_id(self, provider_name: str, task_type: str) -> str:
        return self._select_model_id(provider_name, task_type)

    def resolve(self, request: LLMRequest) -> ProviderRoute:
        providers = self.config.get("providers", {})
        active_provider = self.get_active_provider()

        requested_provider = request.metadata.get("force_provider")
        provider_name = requested_provider or active_provider

        if not self._is_enabled(provider_name, providers):
            standby_provider = str(self.config.get("standby_provider", ""))
            if standby_provider and self._is_enabled(standby_provider, providers):
                provider_name = standby_provider
                reason = "active_provider_disabled_fallback_to_standby"
            else:
                raise ValueError(
                    f"No enabled provider found. requested={requested_provider!r}, active={active_provider!r}"
                )
        else:
            reason = "forced_by_metadata" if requested_provider else "active_provider"

        model_id = self._select_model_id(provider_name, request.task_type)
        return ProviderRoute(provider=provider_name, model_id=model_id, reason=reason)

    def _is_enabled(self, provider_name: str, providers: JsonDict) -> bool:
        if not provider_name:
            return False
        provider_cfg = providers.get(provider_name, {})
        return bool(provider_cfg.get("enabled", False))

    def _select_model_id(self, provider_name: str, task_type: str) -> str:
        providers = self.config.get("providers", {})
        provider_cfg = providers.get(provider_name, {})

        models = provider_cfg.get("models", [])
        if models:
            ordered = sorted(models, key=lambda item: int(item.get("priority", 99)))
            for model in ordered:
                task_types = model.get("task_types", [])
                if not task_types or task_type in task_types:
                    return str(model["model_id"])

        default_model = provider_cfg.get("default_model")
        if default_model:
            return str(default_model)

        raise ValueError(
            f"No model is configured for provider '{provider_name}' and task_type '{task_type}'."
        )
