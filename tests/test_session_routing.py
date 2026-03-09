"""Anti-regression tests for Telegram Copilot Session Routing.

Covers:
- chat_state.json and active_session_id switching
- Unconditional follow-up capture when clarification is pending (the core bug)
- Reset removes only the active session, not all sessions
- Cancel clarification releases input capture
- Up to 4 sessions per chat
"""
from __future__ import annotations

import tempfile
import time
import types
import unittest

from chat_application_service import ChatApplicationService
from research_context_store import ResearchContextStore
from research_service import ResearchService
from tests.test_chat_application_service import FakeAssistantService
from tests.test_research_service import FakeGateway


class ChatStateAndSessionSwitchingTests(unittest.TestCase):
    """Tests for chat_state.json, active_session_id, and session limits."""

    def test_up_to_4_sessions_in_one_chat(self):
        with tempfile.TemporaryDirectory() as td:
            store = ResearchContextStore(base_dir=td, max_sessions_per_chat=4)
            for i in range(4):
                if i > 0:
                    time.sleep(1.1)  # ensure unique timestamp-based names
                store._create_session("chat-1")

            sessions = store.list_sessions("chat-1")
            self.assertEqual(len(sessions), 4)

    def test_set_active_session_id_changes_active_session(self):
        with tempfile.TemporaryDirectory() as td:
            store = ResearchContextStore(base_dir=td, max_sessions_per_chat=4)
            store.save_turn("chat-1", "q1", "r1")
            first_session = store.list_sessions("chat-1")[0]

            time.sleep(1.1)
            store._create_session("chat-1")
            store.save_turn("chat-1", "q2", "r2")
            sessions = store.list_sessions("chat-1")
            self.assertEqual(len(sessions), 2)

            # Switch back to first
            store.set_active_session_id("chat-1", first_session.session_id)
            active = store.get_or_create_active_session("chat-1")
            self.assertEqual(active.session_id, first_session.session_id)

    def test_set_active_session_id_rejects_nonexistent(self):
        with tempfile.TemporaryDirectory() as td:
            store = ResearchContextStore(base_dir=td)
            store.save_turn("chat-1", "q", "r")
            result = store.set_active_session_id("chat-1", "nonexistent-session")
            self.assertFalse(result)

    def test_active_session_id_persists_in_chat_state_json(self):
        with tempfile.TemporaryDirectory() as td:
            store = ResearchContextStore(base_dir=td)
            store.save_turn("chat-1", "q", "r")
            session = store.list_sessions("chat-1")[0]
            store.set_active_session_id("chat-1", session.session_id)

            # Re-create store (simulates restart)
            store2 = ResearchContextStore(base_dir=td)
            self.assertEqual(store2.get_active_session_id("chat-1"), session.session_id)

    def test_followup_goes_to_switched_session_copilot_id(self):
        """After switching active session, follow-up uses the correct copilot_session_id."""
        with tempfile.TemporaryDirectory() as td:
            store = ResearchContextStore(base_dir=td, max_sessions_per_chat=4)
            gateway = FakeGateway([
                "[CONFIRMED] first\nhttps://example.com/1",
                "[CONFIRMED] second\nhttps://example.com/2",
                "[CONFIRMED] follow-up on first\nhttps://example.com/3",
            ])
            service = ResearchService(gateway=gateway, context_store=store)

            service.execute(chat_id="chat-1", user_text="Исследуй тему A")
            first_copilot_id = gateway.requests[0].metadata["copilot_session_id"]

            time.sleep(1.1)
            store._create_session("chat-1")
            service.execute(chat_id="chat-1", user_text="Исследуй тему B")
            second_copilot_id = gateway.requests[1].metadata["copilot_session_id"]

            self.assertNotEqual(first_copilot_id, second_copilot_id)

            # Switch back to first session
            sessions = store.list_sessions("chat-1")
            store.set_active_session_id("chat-1", sessions[0].session_id)
            service.execute(chat_id="chat-1", user_text="Подробнее", mode_hint="followup")
            third_copilot_id = gateway.requests[2].metadata["copilot_session_id"]

            self.assertEqual(first_copilot_id, third_copilot_id)


class UnconditionalFollowUpCaptureTests(unittest.TestCase):
    """Core bug regression: arbitrary text MUST route as follow-up when clarification pending."""

    def test_arbitrary_text_routes_to_research_when_clarification_pending(self):
        """THE BUG SCENARIO: Copilot asks clarifying question, user replies
        with arbitrary text that has NO trigger keywords."""
        with tempfile.TemporaryDirectory() as td:
            gateway = FakeGateway([
                "Пожалуйста, уточните: какой горизонт вас интересует?",
                "[CONFIRMED] Результат\nhttps://example.com/1",
            ])
            research = ResearchService(
                gateway=gateway,
                context_store=ResearchContextStore(base_dir=td),
            )
            service = ChatApplicationService(
                assistant_service=FakeAssistantService(),
                research_service=research,
            )

            # Step 1: initial research request
            first = service.process_text("chat-1", "user-1", 1, "Исследуй рынок ИИ")
            self.assertIn("уточните", first.text)

            # Step 2: user replies with arbitrary text (no keywords!)
            second = service.process_text("chat-1", "user-1", 2, "да, расскажи всё")
            # Must go to research, NOT to AssistantService
            self.assertIn("🔎", second.text)

    def test_arbitrary_number_routes_to_research_when_clarification_pending(self):
        with tempfile.TemporaryDirectory() as td:
            gateway = FakeGateway([
                "Ответьте на эти вопросы: 1) срок? 2) бюджет?",
                "[CONFIRMED] OK\nhttps://example.com/1",
            ])
            research = ResearchService(
                gateway=gateway,
                context_store=ResearchContextStore(base_dir=td),
            )
            service = ChatApplicationService(
                assistant_service=FakeAssistantService(),
                research_service=research,
            )

            service.process_text("chat-1", "user-1", 1, "Исследуй рынок")
            second = service.process_text("chat-1", "user-1", 2, "5 лет, 100к")
            self.assertIn("🔎", second.text)

    def test_without_pending_clarification_arbitrary_text_goes_to_assistant(self):
        """When no clarification is pending, arbitrary text should NOT be captured."""
        with tempfile.TemporaryDirectory() as td:
            gateway = FakeGateway([
                "[CONFIRMED] Финальный ответ\nhttps://example.com/1",
            ])
            research = ResearchService(
                gateway=gateway,
                context_store=ResearchContextStore(base_dir=td),
            )
            assistant = FakeAssistantService(
                {"success": True, "action": "note", "message": "Заметка сохранена"}
            )
            service = ChatApplicationService(
                assistant_service=assistant,
                research_service=research,
            )

            service.process_text("chat-1", "user-1", 1, "Исследуй рынок")
            # The response is a final answer (no clarification hints)
            second = service.process_text("chat-1", "user-1", 2, "купи молоко")
            # Should go to assistant, not research
            self.assertEqual(second.text, "Заметка сохранена")


class ResetOnlyActiveSessionTests(unittest.TestCase):
    def test_reset_removes_only_active_session(self):
        with tempfile.TemporaryDirectory() as td:
            store = ResearchContextStore(base_dir=td, max_sessions_per_chat=4)
            store.save_turn("chat-1", "q1", "r1")
            time.sleep(1.1)
            store._create_session("chat-1")
            store.save_turn("chat-1", "q2", "r2")

            sessions_before = store.list_sessions("chat-1")
            self.assertEqual(len(sessions_before), 2)

            store.reset_chat("chat-1")

            sessions_after = store.list_sessions("chat-1")
            self.assertEqual(len(sessions_after), 1)
            self.assertEqual(sessions_after[0].session_id, sessions_before[0].session_id)

    def test_cancel_clarification_then_reset_preserves_other_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            store = ResearchContextStore(base_dir=td, max_sessions_per_chat=4)
            store.save_turn("chat-1", "q1", "Пожалуйста, уточните вопрос")
            time.sleep(1.1)
            store._create_session("chat-1")
            store.save_turn("chat-1", "q2", "Результат")

            self.assertEqual(len(store.list_sessions("chat-1")), 2)

            # Cancel clarification on the active (second) session
            store.cancel_clarification("chat-1")
            self.assertFalse(store.is_clarification_pending("chat-1"))

            # Reset active session
            store.reset_chat("chat-1")
            remaining = store.list_sessions("chat-1")
            self.assertEqual(len(remaining), 1)


class CancelClarificationTests(unittest.TestCase):
    def test_cancel_clarification_stops_input_capture(self):
        with tempfile.TemporaryDirectory() as td:
            store = ResearchContextStore(base_dir=td)
            store.save_turn("chat-1", "Исследуй", "Пожалуйста, уточните период")
            service = ResearchService(gateway=FakeGateway(["ok"]), context_store=store)

            self.assertTrue(service.should_followup("chat-1", "любой текст"))
            service.cancel_clarification("chat-1")
            self.assertFalse(service.should_followup("chat-1", "любой текст"))

    def test_cancel_on_empty_chat_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            store = ResearchContextStore(base_dir=td)
            self.assertFalse(store.cancel_clarification("nonexistent"))


class TelegramCallbackRoutingTests(unittest.TestCase):
    """Verify switch_research_ callbacks don't collide with confirm/cancel/edit callbacks."""

    def test_switch_research_callback_data_format(self):
        session_id = "session-20260309-120000"
        callback_data = f"switch_research_{session_id}"
        self.assertTrue(callback_data.startswith("switch_research_"))
        extracted = callback_data.replace("switch_research_", "", 1)
        self.assertEqual(extracted, session_id)

    def test_confirm_callback_not_confused_with_switch(self):
        confirm_data = "confirm_user-1_123"
        self.assertFalse(confirm_data.startswith("switch_research_"))

    def test_switch_research_session_via_store(self):
        with tempfile.TemporaryDirectory() as td:
            store = ResearchContextStore(base_dir=td, max_sessions_per_chat=4)
            store.save_turn("chat-1", "q1", "r1")
            time.sleep(1.1)
            store._create_session("chat-1")
            store.save_turn("chat-1", "q2", "r2")

            sessions = store.list_sessions("chat-1")
            first_id = sessions[0].session_id

            result = store.set_active_session_id("chat-1", first_id)
            self.assertTrue(result)
            self.assertEqual(store.get_active_session_id("chat-1"), first_id)


if __name__ == "__main__":
    unittest.main()
