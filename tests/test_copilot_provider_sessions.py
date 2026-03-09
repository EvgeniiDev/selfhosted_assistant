from __future__ import annotations

import types
import unittest
from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest.mock import patch

from integrations.copilot_sdk.provider import CopilotSDKProvider, CopilotTimeoutError
from llm_core import LLMGateway, LLMRequest, LLMRouter


class _TimeoutRuntime:
    def run(self, coroutine, timeout_seconds=None):
        coroutine.close()
        raise FutureTimeoutError()


class FakeSession:
    def __init__(self, session_id: str):
        self.id = session_id
        self.sent_prompts: list[str] = []
        self.destroy_calls = 0

    async def send_and_wait(self, options, timeout: float):
        self.sent_prompts.append(options.prompt)
        return types.SimpleNamespace(type="message", data=types.SimpleNamespace(content=f"reply:{options.prompt}"))

    async def get_messages(self):
        return []

    async def destroy(self):
        self.destroy_calls += 1


class FakeCopilotClient:
    instances: list["FakeCopilotClient"] = []

    def __init__(self):
        self.started = False
        self.stopped = False
        self.create_session_calls = 0
        self.created_configs = []
        self.sessions: dict[str, FakeSession] = {}
        FakeCopilotClient.instances.append(self)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def get_auth_status(self):
        return types.SimpleNamespace(isAuthenticated=True, authType="fake", login="tester")

    async def create_session(self, config):
        self.create_session_calls += 1
        self.created_configs.append(config)
        session_id = getattr(config, "session_id", "ephemeral") or "ephemeral"
        session = self.sessions.get(session_id)
        if session is None:
            session = FakeSession(session_id)
            self.sessions[session_id] = session
        return session


class FakeMessageOptions:
    def __init__(self, prompt: str):
        self.prompt = prompt


class FakeSessionConfig:
    __annotations__ = {
        "model": str,
        "client_name": str,
        "streaming": bool,
        "on_permission_request": object,
        "session_id": str,
        "working_directory": str,
        "skill_directories": list[str],
        "disabled_skills": list[str],
        "mcp_servers": dict[str, dict[str, object]],
    }

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class CopilotProviderPersistentSessionTests(unittest.TestCase):
    def test_attaches_tavily_mcp_when_requested_and_configured(self):
        FakeCopilotClient.instances.clear()

        with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test-key"}, clear=False), patch(
            "integrations.copilot_sdk.provider.CopilotClient", FakeCopilotClient
        ), patch("integrations.copilot_sdk.provider.MessageOptions", FakeMessageOptions), patch(
            "integrations.copilot_sdk.provider.SessionConfig", FakeSessionConfig
        ):
            provider = CopilotSDKProvider()
            provider.generate(
                request=LLMRequest(
                    content="hello",
                    task_type="research",
                    metadata={"mcp_server": "tavily"},
                    text_only=True,
                    allow_mcp_tools=True,
                ),
                model_id="gpt-4.1",
            )

            client = FakeCopilotClient.instances[0]
            config = client.created_configs[0]
            self.assertTrue(hasattr(config, "mcp_servers"))
            self.assertIn("tavily", config.mcp_servers)
            self.assertEqual(config.mcp_servers["tavily"]["command"], "npx")
            self.assertEqual(config.mcp_servers["tavily"]["args"], ["-y", "tavily-mcp@latest"])
            self.assertEqual(config.mcp_servers["tavily"]["env"]["TAVILY_API_KEY"], "tvly-test-key")
            provider.close()

    def test_reuses_persistent_session_between_requests(self):
        FakeCopilotClient.instances.clear()

        with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test-key"}, clear=False), patch(
            "integrations.copilot_sdk.provider.CopilotClient", FakeCopilotClient
        ), patch("integrations.copilot_sdk.provider.MessageOptions", FakeMessageOptions), patch(
            "integrations.copilot_sdk.provider.SessionConfig", FakeSessionConfig
        ):
            provider = CopilotSDKProvider()
            request = LLMRequest(
                content="first",
                task_type="research",
                metadata={"copilot_session_id": "chat-session-1", "mcp_server": "tavily"},
                text_only=True,
                allow_mcp_tools=True,
            )
            provider.generate(request=request, model_id="gpt-4.1")
            provider.generate(
                request=LLMRequest(
                    content="second",
                    task_type="research",
                    metadata={"copilot_session_id": "chat-session-1", "mcp_server": "tavily"},
                    text_only=True,
                    allow_mcp_tools=True,
                ),
                model_id="gpt-4.1",
            )

            client = FakeCopilotClient.instances[0]
            session = client.sessions["chat-session-1"]
            self.assertEqual(client.create_session_calls, 1)
            self.assertEqual(session.sent_prompts, ["first", "second"])
            self.assertEqual(session.destroy_calls, 0)
            provider.close()

    def test_ephemeral_session_is_destroyed_after_request(self):
        FakeCopilotClient.instances.clear()

        with patch("integrations.copilot_sdk.provider.CopilotClient", FakeCopilotClient), patch(
            "integrations.copilot_sdk.provider.MessageOptions", FakeMessageOptions
        ), patch("integrations.copilot_sdk.provider.SessionConfig", FakeSessionConfig):
            provider = CopilotSDKProvider()
            provider.generate(
                request=LLMRequest(content="hello", task_type="unknown", text_only=True, allow_mcp_tools=False),
                model_id="gpt-4.1",
            )

            client = FakeCopilotClient.instances[0]
            session = client.sessions["ephemeral"]
            self.assertEqual(session.destroy_calls, 1)
            provider.close()

    def test_timeout_is_normalized_and_runtime_is_reset(self):
        provider = CopilotSDKProvider(timeout_seconds=1)
        original_runtime = provider._runtime
        provider._runtime = _TimeoutRuntime()

        with self.assertRaises(CopilotTimeoutError):
            provider.generate(
                request=LLMRequest(content="hello", task_type="research", text_only=True, allow_mcp_tools=True),
                model_id="gpt-5.4",
            )

        self.assertIsNone(provider._client)
        self.assertIsNone(provider._client_lock)
        self.assertEqual(provider._persistent_sessions, {})
        self.assertEqual(provider._session_locks, {})
        self.assertIsNot(provider._runtime, original_runtime)

    def test_gateway_raises_copilot_timeout_without_fallback(self):
        provider = CopilotSDKProvider(timeout_seconds=1)
        provider._runtime = _TimeoutRuntime()
        gateway = LLMGateway(
            router=LLMRouter("llm_routing_config.json"),
            providers={"copilot": provider},
        )

        with self.assertRaises(CopilotTimeoutError):
            gateway.generate(
                LLMRequest(
                content="Исследуй тему ИИ",
                task_type="research",
                text_only=True,
                allow_mcp_tools=True,
                )
            )


if __name__ == "__main__":
    unittest.main()