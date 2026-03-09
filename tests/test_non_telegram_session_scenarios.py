from __future__ import annotations

import tempfile
import unittest
from datetime import datetime

from chat_application_service import ChatApplicationService
from models import Task
from research_context_store import ResearchContextStore
from research_service import ResearchService
from tests.test_chat_application_service import FakeAssistantService
from tests.test_research_service import FakeGateway


class NonTelegramSessionScenarioTests(unittest.TestCase):
    def test_same_chat_can_run_research_then_followup_in_one_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            research = ResearchService(
                gateway=FakeGateway(
                    [
                        "[CONFIRMED] Первый вывод\nhttps://example.com/1",
                        "[CONFIRMED] Детализация\nhttps://example.com/2",
                    ]
                ),
                context_store=ResearchContextStore(base_dir=temp_dir),
            )
            service = ChatApplicationService(
                assistant_service=FakeAssistantService(),
                research_service=research,
            )

            first = service.process_text("chat-1", "user-1", 1, "Исследуй рынок ИИ")
            second = service.process_text("chat-1", "user-1", 2, "Подробнее про выводы")

            self.assertIn("🔎 Исследование", first.text)
            self.assertIn("🔎 Follow-up исследование", second.text)
            self.assertEqual(len(research.gateway.requests), 2)
            self.assertEqual(
                research.gateway.requests[0].metadata["copilot_session_id"],
                research.gateway.requests[1].metadata["copilot_session_id"],
            )

    def test_same_chat_can_mix_research_and_task_confirmation_flows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            research = ResearchService(
                gateway=FakeGateway(["[CONFIRMED] Вывод\nhttps://example.com/1"]),
                context_store=ResearchContextStore(base_dir=temp_dir),
            )
            assistant = FakeAssistantService(
                results=[
                    {
                        "success": True,
                        "action": "confirm_task",
                        "task": Task(title="Pay bills", due_time=datetime(2026, 3, 9, 18, 0)),
                        "message": "Confirm task",
                    }
                ]
            )
            service = ChatApplicationService(assistant_service=assistant, research_service=research)

            research_response = service.process_text("chat-1", "user-1", 1, "Исследуй рынок ИИ")
            task_response = service.process_text("chat-1", "user-1", 2, "оплатить счета завтра")
            confirm_response = service.confirm_pending(task_response.pending_id)

            self.assertIn("🔎 Исследование", research_response.text)
            self.assertTrue(task_response.needs_confirmation)
            self.assertEqual(confirm_response.text, "✅ Task created")
            self.assertEqual(len(assistant.confirmed_tasks), 1)

    def test_two_independent_chats_keep_separate_research_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = FakeGateway(
                [
                    "[CONFIRMED] Вывод A\nhttps://example.com/a",
                    "[CONFIRMED] Вывод B\nhttps://example.com/b",
                ]
            )
            research = ResearchService(
                gateway=gateway,
                context_store=ResearchContextStore(base_dir=temp_dir),
            )
            service = ChatApplicationService(
                assistant_service=FakeAssistantService(),
                research_service=research,
            )

            service.process_text("chat-1", "user-1", 1, "Исследуй тему A")
            service.process_text("chat-2", "user-2", 1, "Исследуй тему B")

            self.assertNotEqual(
                gateway.requests[0].metadata["copilot_session_id"],
                gateway.requests[1].metadata["copilot_session_id"],
            )


if __name__ == "__main__":
    unittest.main()