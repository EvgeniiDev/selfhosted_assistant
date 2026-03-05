"""Copilot provider adapter implementing the LLMProvider contract."""

from __future__ import annotations

import asyncio
import inspect
import os
from pathlib import Path
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
        self.working_directory = str(Path(os.getenv("COPILOT_WORKING_DIRECTORY", Path.cwd())).resolve())
        self.skill_directories = self._parse_skill_directories(os.getenv("COPILOT_SKILL_DIRS", ".github/skills"))
        self.disabled_skills = self._parse_csv_list(os.getenv("COPILOT_DISABLED_SKILLS", ""))

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
            session_config = self._build_session_config(selected_model, request)
            session = await client.create_session(
                session_config
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
                    "session_id": str(getattr(session, "id", "")),
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

    def _build_session_config(self, model_id: str, request: LLMRequest) -> SessionConfig:
        kwargs: dict[str, Any] = {
            "model": model_id,
            "client_name": "selfhosted_assistant",
            "streaming": False,
            "on_permission_request": self._approve_all_permissions,
        }

        # SDK versions may expose different SessionConfig fields.
        supported = self._get_session_config_supported_fields()

        requested_session_id = str(request.metadata.get("copilot_session_id", "")).strip()
        if "session_id" in supported and requested_session_id:
            kwargs["session_id"] = requested_session_id

        if "working_directory" in supported and self.working_directory:
            kwargs["working_directory"] = self.working_directory
        if "skill_directories" in supported and self.skill_directories:
            kwargs["skill_directories"] = self.skill_directories
        if "disabled_skills" in supported and self.disabled_skills:
            kwargs["disabled_skills"] = self.disabled_skills

        if "skill_directories" not in supported and self.skill_directories:
            calendar_logger.warning(
                "SessionConfig does not support 'skill_directories' in this SDK version."
            )
        if "disabled_skills" not in supported and self.disabled_skills:
            calendar_logger.warning(
                "SessionConfig does not support 'disabled_skills' in this SDK version."
            )

        return SessionConfig(**kwargs)

    def _get_session_config_supported_fields(self) -> set[str]:
        annotations = getattr(SessionConfig, "__annotations__", None)
        if isinstance(annotations, dict) and annotations:
            return {str(key) for key in annotations.keys()}

        try:
            return set(inspect.signature(SessionConfig).parameters.keys())
        except (TypeError, ValueError):
            return set()

    def _parse_skill_directories(self, raw_value: str) -> list[str]:
        dirs = [part.strip() for part in (raw_value or "").split(";") if part.strip()]
        resolved: list[str] = []
        for item in dirs:
            resolved.append(str(Path(item).resolve()))
        return resolved

    def _parse_csv_list(self, raw_value: str) -> list[str]:
        return [part.strip() for part in (raw_value or "").split(",") if part.strip()]
