"""OpenRouter standby provider adapter implementing the LLMProvider contract."""

from __future__ import annotations

import os

import requests

from llm_core.contracts import LLMRequest, LLMResponse


class OpenRouterStandbyProvider:
    """OpenRouter provider kept as standby and activated by routing config."""

    name = "openrouter"

    def __init__(
        self,
        api_url: str = "https://openrouter.ai/api/v1/chat/completions",
        timeout_seconds: int = 120,
    ):
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.api_key = os.getenv("OPEN_ROUTER_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, request: LLMRequest, model_id: str) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("OPEN_ROUTER_API_KEY is missing.")

        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.content})

        payload = {
            "model": model_id,
            "messages": messages,
            "provider": {
                "allow_fallbacks": True,
                "sort": {"by": "throughput", "partition": "none"},
            },
        }

        response = requests.post(
            self.api_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"OpenRouter request failed status={response.status_code}, body={response.text[:400]}"
            )

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("OpenRouter response does not contain choices.")

        content = (
            choices[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        usage = data.get("usage", {}) if isinstance(data.get("usage"), dict) else {}
        return LLMResponse(
            content=content,
            provider=self.name,
            model_id=str(data.get("model", model_id)),
            usage=usage,
            trace={"route": "standby"},
            raw_meta={"id": data.get("id")},
        )
