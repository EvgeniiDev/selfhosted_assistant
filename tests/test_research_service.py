from __future__ import annotations

import tempfile
import unittest

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
            self.assertIn("Контекст предыдущего исследования", gateway.requests[1].content)
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
            self.assertIn("Контекст предыдущего исследования", gateway.requests[1].content)
            self.assertIn("Контекст предыдущего исследования", gateway.requests[2].content)

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


if __name__ == "__main__":
    unittest.main()