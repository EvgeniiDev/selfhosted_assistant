"""Copilot provider adapter implementing the LLMProvider contract."""

from __future__ import annotations

import asyncio
import os
from time import sleep
from typing import Any, cast

from copilot import (
    CopilotClient,
    MessageOptions,
    PermissionHandler,
    PermissionRequestResult,
    SessionConfig,
)

from llm_core.contracts import LLMRequest, LLMResponse
from logger import calendar_logger


class CopilotProviderError(RuntimeError):
    """Base class for normalized Copilot provider errors."""


class CopilotAuthError(CopilotProviderError):
    """Authentication/authorization failure when calling Copilot endpoint."""


class CopilotSDKProvider:
    """Adapter built on the official `github-copilot-sdk` Python package."""

    name = "copilot"

    @staticmethod
    def _approve_all_permissions(request: Any, invocation: Any) -> PermissionRequestResult:
        return cast(PermissionRequestResult, PermissionHandler.approve_all(request, invocation))

    def __init__(self, timeout_seconds: int = 90, retries: int = 2):
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.model_fallback = os.getenv("COPILOT_MODEL", "gpt-4.1")

    def is_available(self) -> bool:
        try:
            status = self._run_async(self._get_auth_status())
            return bool(getattr(status, "isAuthenticated", False))
        except Exception:
            return False

    def generate(self, request: LLMRequest, model_id: str) -> LLMResponse:
        # Keep prompt logging format stable for existing observability.
        self._build_messages(request)

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 2):
            try:
                response = self._run_async(
                    self._generate_with_sdk(
                        request=request,
                        model_id=model_id,
                        attempt=attempt,
                    )
                )
                return response

            except CopilotAuthError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt <= self.retries:
                    sleep(0.5 * attempt)

        raise CopilotProviderError(f"Copilot retries exhausted: {last_error}")

    async def _get_auth_status(self):
        client = CopilotClient()
        await client.start()
        try:
            return await client.get_auth_status()
        finally:
            await client.stop()

    async def _generate_with_sdk(self, request: LLMRequest, model_id: str, attempt: int) -> LLMResponse:
        client = CopilotClient()
        await client.start()
        session = None
        try:
            auth = await client.get_auth_status()
            if not getattr(auth, "isAuthenticated", False):
                raise CopilotAuthError(
                    "Copilot auth is not configured. Run `gh auth login` for github.com."
                )

            selected_model = model_id or self.model_fallback
            session = await client.create_session(
                SessionConfig(
                    model=selected_model,
                    client_name="selfhosted_assistant",
                    streaming=False,
                    on_permission_request=self._approve_all_permissions,
                )
            )

            event = await session.send_and_wait(
                MessageOptions(prompt=request.content),
                timeout=float(self.timeout_seconds),
            )

            content = self._extract_content_from_event(event)
            if not content:
                messages = await session.get_messages()
                content = self._extract_content_from_messages(messages)

            if not content:
                raise CopilotProviderError("Copilot SDK response content is empty.")

            return LLMResponse(
                content=content,
                provider=self.name,
                model_id=selected_model,
                usage={},
                trace={"attempt": attempt, "auth_type": getattr(auth, "authType", "unknown")},
                raw_meta={
                    "event_type": str(getattr(event, "type", "")) if event else "",
                    "login": getattr(auth, "login", ""),
                },
            )
        finally:
            if session is not None:
                try:
                    await session.destroy()
                except Exception:
                    pass
            await client.stop()

    def _extract_content_from_event(self, event: Any) -> str:
        if not event:
            return ""
        data = getattr(event, "data", None)
        content = getattr(data, "content", None)
        return str(content).strip() if content else ""

    def _extract_content_from_messages(self, messages: list[Any]) -> str:
        for message in reversed(messages or []):
            data = getattr(message, "data", None)
            content = getattr(data, "content", None)
            if content:
                return str(content).strip()
        return ""

    def _run_async(self, coroutine):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        # If we are already inside an event loop (e.g. Telegram async handler),
        # execute SDK async flow in a dedicated thread with its own loop.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(coroutine))
            return future.result()

    def _build_messages(self, request: LLMRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.content})
        calendar_logger.log_llm_prompt(request.content, request.system_prompt)
        return messages
