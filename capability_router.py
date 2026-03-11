from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from capability_registry import CapabilityRegistry, CapabilitySpec


@dataclass(slots=True)
class CapabilityRoute:
    capability_id: str
    execution_mode: Literal["skill", "legacy"]
    spec: CapabilitySpec | None = None


class CapabilityRouter:
    """Resolves whether a capability should run through skills or legacy code."""

    def __init__(self, registry: CapabilityRegistry | None = None) -> None:
        self.registry = registry or CapabilityRegistry()

    def resolve(self, capability_id: str) -> CapabilityRoute:
        if self.registry.has(capability_id):
            return CapabilityRoute(
                capability_id=capability_id,
                execution_mode="skill",
                spec=self.registry.get(capability_id),
            )

        return CapabilityRoute(
            capability_id=capability_id,
            execution_mode="legacy",
            spec=None,
        )

    def is_skill_backed(self, capability_id: str) -> bool:
        return self.resolve(capability_id).execution_mode == "skill"