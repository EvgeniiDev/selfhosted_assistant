"""Copilot provider adapter implementing the LLMProvider contract."""

from __future__ import annotations

import atexit
import asyncio
import json
import inspect
import os
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
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


class _AsyncLoopThread:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_lock = threading.Lock()

    def run(self, coroutine, timeout_seconds: float | None = None):
        self._ensure_started()
        if self._loop is None:
            raise RuntimeError("Copilot async runtime loop is not available.")

        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            if timeout_seconds is None:
                return future.result()
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            raise

    def stop(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return

        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        self._loop = None
        self._thread = None
        self._ready.clear()

    def is_started(self) -> bool:
        return self._loop is not None and self._thread is not None

    def _ensure_started(self) -> None:
        if self.is_started():
            return

        with self._start_lock:
            if self.is_started():
                return

            self._thread = threading.Thread(target=self._thread_main, name="copilot-sdk-loop", daemon=True)
            self._thread.start()
            self._ready.wait(timeout=5)
            if not self.is_started():
                raise RuntimeError("Failed to start Copilot async runtime loop.")

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()

        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()


class CopilotProviderError(RuntimeError):
    """Base class for normalized Copilot provider errors."""


class CopilotAuthError(CopilotProviderError):
    """Authentication/authorization failure when calling Copilot endpoint."""


class CopilotTimeoutError(CopilotProviderError):
    """Timeout raised when the Copilot SDK call does not finish in time."""


class CopilotSDKProvider:
    """Adapter built on the official `github-copilot-sdk` Python package."""

    name = "copilot"

    @staticmethod
    def _approve_all_permissions(request: Any, invocation: Any) -> PermissionRequestResult:
        return cast(PermissionRequestResult, PermissionHandler.approve_all(request, invocation))

    def __init__(self, timeout_seconds: int = 300, retries: int = 2):
        self.timeout_seconds = int(timeout_seconds)
        self.retries = retries
        self.model_fallback = os.getenv("COPILOT_MODEL", "gpt-4.1")
        self.working_directory = str(Path(os.getenv("COPILOT_WORKING_DIRECTORY", Path.cwd())).resolve())
        self.skill_directories = self._parse_skill_directories(os.getenv("COPILOT_SKILL_DIRS", ".github/skills"))
        self.disabled_skills = self._parse_csv_list(os.getenv("COPILOT_DISABLED_SKILLS", ""))
        self._runtime = _AsyncLoopThread()
        self._client: CopilotClient | None = None
        self._client_lock: asyncio.Lock | None = None
        self._persistent_sessions: dict[str, Any] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._closed = False
        atexit.register(self.close)

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
                    ),
                    timeout_seconds=self._operation_timeout_seconds(),
                )
                return response

            except CopilotAuthError:
                raise
            except CopilotTimeoutError:
                self._reset_runtime_after_timeout()
                raise
            except Exception as exc:
                last_error = exc
                if attempt <= self.retries:
                    sleep(0.5 * attempt)

        raise CopilotProviderError(f"Copilot retries exhausted: {last_error}")

    async def _get_auth_status(self):
        client = await self._get_or_start_client()
        return await client.get_auth_status()

    async def _generate_with_sdk(self, request: LLMRequest, model_id: str, attempt: int) -> LLMResponse:
        client = await self._get_or_start_client()
        auth = await client.get_auth_status()
        if not getattr(auth, "isAuthenticated", False):
            raise CopilotAuthError(
                "Copilot auth is not configured. Run `gh auth login` for github.com."
            )

        selected_model = model_id or self.model_fallback
        persistent_session_id = self._get_requested_session_id(request)
        if persistent_session_id:
            return await self._generate_with_persistent_session(
                client=client,
                request=request,
                model_id=selected_model,
                attempt=attempt,
                auth=auth,
                persistent_session_id=persistent_session_id,
            )

        session_config = self._build_session_config(selected_model, request)
        session = await client.create_session(session_config)
        try:
            event, content = await self._send_prompt(session, request)
            return self._build_response(
                content=content,
                selected_model=selected_model,
                attempt=attempt,
                auth=auth,
                event=event,
                session=session,
            )
        finally:
            try:
                await session.destroy()
            except Exception:
                pass

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

    def _run_async(self, coroutine, timeout_seconds: float | None = None):
        try:
            return self._runtime.run(coroutine, timeout_seconds=timeout_seconds)
        except FutureTimeoutError as exc:
            limit = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
            raise CopilotTimeoutError(
                f"Copilot SDK operation exceeded {limit:.1f}s and was aborted."
            ) from exc

    def _operation_timeout_seconds(self) -> float:
        return max(float(self.timeout_seconds) + 15.0, float(self.timeout_seconds) * 1.25)

    def _reset_runtime_after_timeout(self) -> None:
        calendar_logger.warning(
            "Copilot runtime timed out; resetting client/session state before surfacing the error."
        )
        self._persistent_sessions = {}
        self._session_locks = {}
        self._client = None
        self._client_lock = None
        self._runtime = _AsyncLoopThread()

    def _build_messages(self, request: LLMRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.content})
        calendar_logger.log_llm_prompt(request.content, request.system_prompt)
        return messages

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        if self._runtime.is_started():
            try:
                self._runtime.run(self._shutdown_async())
            except Exception:
                pass
        self._runtime.stop()

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

        mcp_servers = self._build_mcp_servers(request)
        if "mcp_servers" in supported and mcp_servers:
            kwargs["mcp_servers"] = mcp_servers

        if "skill_directories" not in supported and self.skill_directories:
            calendar_logger.warning(
                "SessionConfig does not support 'skill_directories' in this SDK version."
            )
        if "disabled_skills" not in supported and self.disabled_skills:
            calendar_logger.warning(
                "SessionConfig does not support 'disabled_skills' in this SDK version."
            )
        if "mcp_servers" not in supported and mcp_servers:
            calendar_logger.warning(
                "SessionConfig does not support 'mcp_servers' in this SDK version. Tavily MCP will be unavailable."
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

    def _build_mcp_servers(self, request: LLMRequest) -> dict[str, dict[str, Any]]:
        if not request.allow_mcp_tools:
            return {}

        requested_server = str(request.metadata.get("mcp_server", "")).strip().lower()
        if requested_server and requested_server != "tavily":
            return {}

        tavily_api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if not tavily_api_key:
            calendar_logger.warning(
                "TAVILY_API_KEY is not configured; Tavily MCP will not be attached to the Copilot session."
            )
            return {}

        env = {"TAVILY_API_KEY": tavily_api_key}
        default_parameters = os.getenv("TAVILY_DEFAULT_PARAMETERS", "").strip()
        if default_parameters:
            try:
                json.loads(default_parameters)
            except json.JSONDecodeError:
                calendar_logger.warning(
                    "TAVILY_DEFAULT_PARAMETERS is not valid JSON and will be ignored."
                )
            else:
                env["DEFAULT_PARAMETERS"] = default_parameters

        return {
            "tavily": {
                "type": "local",
                "command": "npx",
                "args": ["-y", "tavily-mcp@latest"],
                "env": env,
                "tools": ["*"],
                "timeout": 30000,
            }
        }

    def _get_requested_session_id(self, request: LLMRequest) -> str:
        return str(request.metadata.get("copilot_session_id", "")).strip()

    def _build_response(
        self,
        content: str,
        selected_model: str,
        attempt: int,
        auth: Any,
        event: Any,
        session: Any,
    ) -> LLMResponse:
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

    async def _send_prompt(self, session: Any, request: LLMRequest) -> tuple[Any, str]:
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

        return event, content

    async def _generate_with_persistent_session(
        self,
        client: CopilotClient,
        request: LLMRequest,
        model_id: str,
        attempt: int,
        auth: Any,
        persistent_session_id: str,
    ) -> LLMResponse:
        session_config = self._build_session_config(model_id, request)
        session_lock = self._session_locks.get(persistent_session_id)
        if session_lock is None:
            session_lock = asyncio.Lock()
            self._session_locks[persistent_session_id] = session_lock

        async with session_lock:
            session = self._persistent_sessions.get(persistent_session_id)
            if session is None:
                session = await client.create_session(session_config)
                self._persistent_sessions[persistent_session_id] = session

            try:
                event, content = await self._send_prompt(session, request)
            except Exception:
                await self._destroy_persistent_session(persistent_session_id)
                session = await client.create_session(session_config)
                self._persistent_sessions[persistent_session_id] = session
                event, content = await self._send_prompt(session, request)

            return self._build_response(
                content=content,
                selected_model=model_id,
                attempt=attempt,
                auth=auth,
                event=event,
                session=session,
            )

    async def _get_or_start_client(self) -> CopilotClient:
        if self._client_lock is None:
            self._client_lock = asyncio.Lock()

        async with self._client_lock:
            if self._client is None:
                client = CopilotClient()
                await client.start()
                self._client = client
        if self._client is None:
            raise RuntimeError("Copilot client failed to start.")
        return self._client

    async def _destroy_persistent_session(self, persistent_session_id: str) -> None:
        session = self._persistent_sessions.pop(persistent_session_id, None)
        if session is None:
            return

        try:
            await session.destroy()
        except Exception:
            pass

    async def _shutdown_async(self) -> None:
        session_ids = list(self._persistent_sessions.keys())
        for session_id in session_ids:
            await self._destroy_persistent_session(session_id)

        if self._client is not None:
            try:
                await self._client.stop()
            finally:
                self._client = None
                self._client_lock = None
