from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from capability_registry import CapabilityRegistry
from llm_core.contracts import LLMResponse
from research_context_store import ResearchContextStore
from research_service import ResearchService


class FakeGateway:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        response_text = self.responses.pop(0)
        return LLMResponse(
            content=response_text,
            provider="fake",
            model_id="fake-model",
        )


class ResearchServiceTests(unittest.TestCase):
    def test_research_uses_capability_registry_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "capabilities.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "capabilities": {
                            "research": {
                                "skill_name": "custom-research-skill",
                                "task_type": "research",
                                "system_prompt": "Use the custom research contract.",
                                "mcp_server": "docs-fetch",
                                "text_only": True,
                                "allow_mcp_tools": True,
                                "context_policy": {
                                    "include_brief": True,
                                    "include_findings": False,
                                    "include_sources": True,
                                    "max_findings": 3,
                                    "max_sources": 1
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            store = ResearchContextStore(base_dir=temp_dir)
            store.save_turn("chat-1", "Исследуй тему", "[CONFIRMED] Факт\nhttps://example.com/1\nhttps://example.com/2")
            store.save_artifacts(
                "chat-1",
                "Краткий итог\n[CONFIRMED] Факт A\n[CONFIRMED] Факт B\nhttps://example.com/1\nhttps://example.com/2",
            )
            gateway = FakeGateway(["[CONFIRMED] Результат\nhttps://example.com/out"])
            service = ResearchService(
                gateway=gateway,
                context_store=store,
                capability_registry=CapabilityRegistry(config_path=registry_path),
            )

            service.execute(chat_id="chat-1", user_text="Подробнее", mode_hint="followup")

            request = gateway.requests[0]
            self.assertEqual(request.metadata.get("skill_name"), "custom-research-skill")
            self.assertEqual(request.metadata.get("mcp_server"), "docs-fetch")
            self.assertEqual(request.system_prompt, "Use the custom research contract.")
            self.assertIn("Use skill `custom-research-skill`", request.content)
            self.assertIn('"sources": [', request.content)
            self.assertNotIn('"findings": [', request.content)

    def test_followup_uses_same_copilot_session_and_saved_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchContextStore(base_dir=temp_dir)
            gateway = FakeGateway(
                [
                    "[CONFIRMED] Первый факт\nhttps://example.com/1",
                    "[CONFIRMED] Follow-up факт\nhttps://example.com/2",
                ]
            )
            service = ResearchService(gateway=gateway, context_store=store)

            first = service.execute(chat_id="chat-1", user_text="Исследуй тему тестирования")
            second = service.execute(chat_id="chat-1", user_text="Подробнее про выводы", mode_hint="followup")

            self.assertEqual(first.mode, "new")
            self.assertEqual(second.mode, "followup")
            self.assertEqual(len(gateway.requests), 2)
            self.assertEqual(
                gateway.requests[0].metadata.get("copilot_session_id"),
                gateway.requests[1].metadata.get("copilot_session_id"),
            )
            self.assertIn("Use skill `research-pipeline`", gateway.requests[1].content)
            self.assertIn("- mode: followup", gateway.requests[1].content)
            self.assertIn("Host context JSON:", gateway.requests[1].content)
            self.assertIn("https://example.com/2", second.sources)

    def test_multiple_requests_in_same_chat_reuse_same_session_across_three_turns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchContextStore(base_dir=temp_dir)
            gateway = FakeGateway(
                [
                    "[CONFIRMED] Первый факт\nhttps://example.com/1",
                    "[CONFIRMED] Второй факт\nhttps://example.com/2",
                    "[CONFIRMED] Третий факт\nhttps://example.com/3",
                ]
            )
            service = ResearchService(gateway=gateway, context_store=store)

            service.execute(chat_id="chat-1", user_text="Исследуй тему тестирования")
            second = service.execute(chat_id="chat-1", user_text="Подробнее про выводы", mode_hint="followup")
            third = service.execute(chat_id="chat-1", user_text="Раскрой риски", mode_hint="followup")

            session_ids = [request.metadata.get("copilot_session_id") for request in gateway.requests]
            self.assertEqual(session_ids, [session_ids[0], session_ids[0], session_ids[0]])
            self.assertEqual(second.mode, "followup")
            self.assertEqual(third.mode, "followup")
            self.assertIn("Host context JSON:", gateway.requests[1].content)
            self.assertIn("Host context JSON:", gateway.requests[2].content)

    def test_different_chats_get_different_research_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchContextStore(base_dir=temp_dir)
            gateway = FakeGateway(
                [
                    "[CONFIRMED] Факт A\nhttps://example.com/a",
                    "[CONFIRMED] Факт B\nhttps://example.com/b",
                ]
            )
            service = ResearchService(gateway=gateway, context_store=store)

            service.execute(chat_id="chat-1", user_text="Исследуй тему A")
            service.execute(chat_id="chat-2", user_text="Исследуй тему B")

            self.assertNotEqual(
                gateway.requests[0].metadata.get("copilot_session_id"),
                gateway.requests[1].metadata.get("copilot_session_id"),
            )

    def test_followup_hint_without_context_falls_back_to_new_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchContextStore(base_dir=temp_dir)
            service = ResearchService(gateway=FakeGateway(["[CONFIRMED] факт\nhttps://example.com/x"]), context_store=store)

            result = service.execute(chat_id="chat-1", user_text="Подробнее про рынок", mode_hint="followup")

            self.assertEqual(result.mode, "new")

    def test_force_followup_requires_existing_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchContextStore(base_dir=temp_dir)
            service = ResearchService(gateway=FakeGateway(["ok"]), context_store=store)

            self.assertFalse(service.should_followup("chat-1", "Подробнее"))
            self.assertTrue(service.should_start_new("chat-1", "Исследуй рынок агентных систем"))

    def test_clarification_pending_allows_followup_without_explicit_keyword(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchContextStore(base_dir=temp_dir)
            store.save_turn("chat-1", "Исследуй тему", "Пожалуйста, уточните горизонт исследования")
            service = ResearchService(gateway=FakeGateway(["ok"]), context_store=store)

            self.assertTrue(service.should_followup("chat-1", "Меня интересует горизонт в 5 лет"))

    def test_clarification_pending_captures_arbitrary_text_as_followup(self):
        """Core bug regression: arbitrary text MUST route as follow-up
        when a clarification question is pending, even without ANY marker keywords."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchContextStore(base_dir=temp_dir)
            store.save_turn("chat-1", "Исследуй тему", "Пожалуйста, уточните горизонт исследования")
            service = ResearchService(gateway=FakeGateway(["ok"]), context_store=store)

            self.assertTrue(service.should_followup("chat-1", "да"))
            self.assertTrue(service.should_followup("chat-1", "расскажи про медицину"))
            self.assertTrue(service.should_followup("chat-1", "17"))
            self.assertTrue(service.should_followup("chat-1", "всё что найдёшь"))

    def test_no_clarification_pending_arbitrary_text_is_not_followup(self):
        """Without a pending clarification, arbitrary text should NOT be treated as follow-up."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchContextStore(base_dir=temp_dir)
            store.save_turn("chat-1", "Исследуй тему", "Вот результаты исследования:\n[CONFIRMED] факт 1")
            service = ResearchService(gateway=FakeGateway(["ok"]), context_store=store)

            self.assertFalse(service.should_followup("chat-1", "да"))
            self.assertFalse(service.should_followup("chat-1", "расскажи про медицину"))

    def test_cancel_clarification_stops_input_capture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchContextStore(base_dir=temp_dir)
            store.save_turn("chat-1", "Исследуй тему", "Пожалуйста, уточните горизонт")
            service = ResearchService(gateway=FakeGateway(["ok"]), context_store=store)

            self.assertTrue(service.should_followup("chat-1", "любой текст"))
            service.cancel_clarification("chat-1")
            self.assertFalse(service.should_followup("chat-1", "любой текст"))


if __name__ == "__main__":
    unittest.main()