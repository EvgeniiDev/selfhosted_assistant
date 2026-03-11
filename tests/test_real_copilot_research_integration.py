from __future__ import annotations

import os
import re
import tempfile
import unittest

from dotenv import load_dotenv

from integrations.copilot_sdk import CopilotSDKProvider
from llm_core import LLMRequest
from research_context_store import ResearchContextStore
from research_service import ResearchService


load_dotenv()


class _RecordingCopilotGateway:
    def __init__(self, provider: CopilotSDKProvider, model_id: str):
        self.provider = provider
        self.model_id = model_id
        self.requests = []
        self.responses = []

    def generate(self, request: LLMRequest):
        self.requests.append(request)
        response = self.provider.generate(request=request, model_id=self.model_id)
        self.responses.append(response)
        return response


@unittest.skipUnless(
    os.getenv("RUN_REAL_COPILOT_INTEGRATION") == "1",
    "Set RUN_REAL_COPILOT_INTEGRATION=1 to run real Copilot SDK integration tests.",
)
class RealCopilotResearchIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model_id = os.getenv("COPILOT_INTEGRATION_MODEL", "gpt-4.1")
        cls.provider = CopilotSDKProvider(
            timeout_seconds=int(os.getenv("COPILOT_INTEGRATION_TIMEOUT", "120")),
            retries=0,
        )
        if not cls.provider.is_available():
            cls.provider.close()
            raise unittest.SkipTest(
                "Copilot auth is unavailable. Run `gh auth login -h github.com -w` before executing this suite."
            )

    @classmethod
    def tearDownClass(cls):
        cls.provider.close()

    def test_real_provider_research_prompt_returns_content_and_url(self):
        request = LLMRequest(
            content=(
                "Use skill `research-pipeline` from the connected skills as the source of truth.\n"
                "Host runtime context:\n"
                "- skill: research-pipeline\n"
                "- mode: new\n"
                "- user_request: исследуй кратко тему Python package manager uv и укажи официальные URL источников\n"
                "- host_context_available: no\n"
                "Host requirements:\n"
                "- Follow the selected skill's workflow and output contract.\n"
                "- Use the provided mode and host context when relevant.\n"
                "- Return a user-facing answer only.\n"
            ),
            task_type="research",
            system_prompt=(
                "You are a precise assistant executing a connected skill. "
                "Treat the selected skill as the authoritative workflow and output contract."
            ),
            metadata={"mcp_server": "tavily", "skill_name": "research-pipeline"},
            text_only=True,
            allow_mcp_tools=True,
        )

        response = self.provider.generate(request=request, model_id=self.model_id)

        text = (response.content or "").strip()
        self.assertTrue(text)
        self.assertRegex(text, r"https?://")
        self.assertEqual(response.provider, "copilot")
        self.assertTrue(str(response.trace.get("auth_type", "")).strip())

    def test_research_service_multi_turn_session_reuses_real_sdk_session(self):
        gateway = _RecordingCopilotGateway(self.provider, self.model_id)
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ResearchService(
                gateway=gateway,
                context_store=ResearchContextStore(base_dir=temp_dir),
            )

            first = service.execute(
                chat_id="real-sdk-chat-1",
                user_text="Исследуй тему Python package manager uv и укажи официальные URL источников",
            )
            second = service.execute(
                chat_id="real-sdk-chat-1",
                user_text="Подробнее про отличия uv от pip, poetry и pip-tools. Сохрани ссылки.",
                mode_hint="followup",
            )
            third = service.execute(
                chat_id="real-sdk-chat-1",
                user_text="Раскрой риски и ограничения, и добавь новые ссылки если нужно.",
                mode_hint="followup",
            )

            self.assertTrue(first.outbound_text.strip())
            self.assertTrue(second.outbound_text.strip())
            self.assertTrue(third.outbound_text.strip())
            self.assertEqual(second.mode, "followup")
            self.assertEqual(third.mode, "followup")

            response_session_ids = [
                str(response.raw_meta.get("session_id", "")).strip() for response in gateway.responses
            ]
            self.assertEqual(len(response_session_ids), 3)

            if all(response_session_ids):
                self.assertEqual(response_session_ids[0], response_session_ids[1])
                self.assertEqual(response_session_ids[1], response_session_ids[2])

            request_session_ids = [
                str(request.metadata.get("copilot_session_id", "")).strip() for request in gateway.requests
            ]
            self.assertEqual(len(request_session_ids), 3)
            self.assertTrue(all(request_session_ids))
            self.assertEqual(request_session_ids[0], request_session_ids[1])
            self.assertEqual(request_session_ids[1], request_session_ids[2])
            self.assertIn(request_session_ids[0], self.provider._persistent_sessions)

            second_request_prompt = gateway.requests[1].content
            third_request_prompt = gateway.requests[2].content
            self.assertIn("Host context JSON:", second_request_prompt)
            self.assertIn("Host context JSON:", third_request_prompt)

            combined_outputs = "\n".join(response.content for response in gateway.responses if response.content)
            self.assertTrue(combined_outputs.strip())
            self.assertIn("uv", combined_outputs.lower())

            saved_sources = service.list_sources("real-sdk-chat-1")
            if saved_sources:
                self.assertTrue(any(re.match(r"https?://", source) for source in saved_sources))


if __name__ == "__main__":
    unittest.main()