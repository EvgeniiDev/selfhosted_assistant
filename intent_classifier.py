from __future__ import annotations

import re

from capability_registry import CapabilityRegistry, IntentClassificationConfig
from llm_core import LLMGateway, LLMRequest
from logger import calendar_logger


class IntentClassifier:
    """Classifies incoming user messages using registry-configured prompt and heuristics."""

    def __init__(
        self,
        gateway: LLMGateway,
        capability_registry: CapabilityRegistry | None = None,
    ) -> None:
        self.gateway = gateway
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.config = self.capability_registry.get_intent_classification()

    def classify_request(self, user_message: str) -> str:
        try:
            classification = self._classify_with_model(user_message)
            if classification and classification != "unknown":
                return classification

            fallback = self._heuristic_classification(user_message)
            if classification == "unknown":
                calendar_logger.warning(
                    f"IntentClassifier: model returned 'unknown', heuristic override -> {fallback}"
                )
            else:
                calendar_logger.warning(f"IntentClassifier: heuristic fallback used -> {fallback}")
            return fallback
        except Exception as exc:
            calendar_logger.log_error(exc, "IntentClassifier.classify_request")
            return self._heuristic_classification(user_message)

    def _classify_with_model(self, user_message: str) -> str | None:
        request = LLMRequest(
            content=user_message,
            task_type=self.config.task_type,
            system_prompt=self.config.system_prompt,
            metadata={"is_private": True, "handler": "IntentClassifier"},
            text_only=True,
            allow_mcp_tools=False,
        )
        response = self.gateway.generate(request)
        content = (response.content or "").strip().lower()
        if content in self.config.valid_types:
            calendar_logger.info(f"Request classified as: {content}")
            return content

        if content:
            calendar_logger.warning(f"Invalid classification received: {content}")
        return None

    def _heuristic_classification(self, user_message: str) -> str:
        text = (user_message or "").strip().lower()
        if not text:
            return self.config.default_intent

        for keyword in self.config.heuristics.get("list_notes", ()): 
            if keyword in text:
                return "list_notes"

        for keyword in self.config.heuristics.get("research", ()): 
            if keyword in text:
                return "research"

        for keyword in self.config.heuristics.get("task", ()): 
            if keyword in text:
                return "task"

        has_datetime_hint = self._has_datetime_hint(text)
        for keyword in self.config.heuristics.get("calendar_event", ()): 
            if keyword in text and has_datetime_hint:
                return "calendar_event"

        return self.config.default_intent

    def _has_datetime_hint(self, text: str) -> bool:
        if re.search(r"\b\d{1,2}:\d{2}\b", text):
            return True
        if re.search(r"\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b", text):
            return True
        return any(keyword in text for keyword in self.config.datetime_keywords)
