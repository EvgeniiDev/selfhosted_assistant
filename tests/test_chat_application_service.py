from __future__ import annotations

import types
import unittest
from datetime import datetime

from chat_application_service import ChatApplicationService
from models import CalendarEvent, Task


class FakeAssistantService:
    def __init__(self, result=None, results=None, confirm_event_result=None, confirm_task_result=None):
        self.result = result or {"success": True, "action": "note", "message": "note"}
        self.results = list(results or [])
        self.confirmed_events = []
        self.confirmed_tasks = []
        self.process_calls = []
        self.confirm_event_result = confirm_event_result or {
            "success": True,
            "message": "Event created",
            "event_link": "https://example.com/event",
        }
        self.confirm_task_result = confirm_task_result or {"success": True, "message": "Task created"}

    def process_user_request(self, user_message: str):
        self.process_calls.append(user_message)
        if self.results:
            return self.results.pop(0)
        return self.result

    def create_confirmed_event(self, event):
        self.confirmed_events.append(event)
        return self.confirm_event_result

    def create_confirmed_task(self, task):
        self.confirmed_tasks.append(task)
        return self.confirm_task_result


class FakeResearchService:
    def __init__(self):
        self.calls = []

    def should_start_new(self, chat_id: str, user_text: str) -> bool:
        return user_text.startswith("Исследуй")

    def should_followup(self, chat_id: str, user_text: str) -> bool:
        return user_text.startswith("Подробнее")

    def execute(self, chat_id: str, user_text: str, mode_hint: str):
        self.calls.append((chat_id, user_text, mode_hint))
        return types.SimpleNamespace(outbound_text=f"research:{mode_hint}:{user_text}")


class ChatApplicationServiceTests(unittest.TestCase):
    def test_process_text_returns_note_response(self):
        service = ChatApplicationService(
            assistant_service=FakeAssistantService(
                {"success": True, "action": "note", "message": "Saved note"}
            ),
            research_service=FakeResearchService(),
        )

        response = service.process_text("chat-1", "user-1", 1, "remember this")

        self.assertEqual(response.text, "Saved note")
        self.assertEqual(response.parse_mode, "Markdown")
        self.assertFalse(response.needs_confirmation)

    def test_process_text_returns_list_notes_response(self):
        service = ChatApplicationService(
            assistant_service=FakeAssistantService(
                {"success": True, "action": "list_notes", "message": "Notes list"}
            ),
            research_service=FakeResearchService(),
        )

        response = service.process_text("chat-1", "user-1", 1, "show my notes")

        self.assertEqual(response.text, "Notes list")
        self.assertEqual(response.parse_mode, "Markdown")
        self.assertFalse(response.needs_confirmation)

    def test_process_text_returns_confirmation_for_task(self):
        assistant = FakeAssistantService(
            {
                "success": True,
                "action": "confirm_task",
                "task": Task(title="Pay bills", due_time=datetime(2026, 3, 9, 18, 0)),
                "message": "Confirm task",
            }
        )
        service = ChatApplicationService(assistant_service=assistant, research_service=FakeResearchService())

        response = service.process_text("chat-1", "user-1", 123, "pay bills")

        self.assertTrue(response.needs_confirmation)
        self.assertEqual(response.parse_mode, "Markdown")
        self.assertEqual(response.pending_id, "user-1_123")

    def test_process_text_returns_error_response_when_assistant_fails(self):
        service = ChatApplicationService(
            assistant_service=FakeAssistantService({"success": False, "message": "Could not parse"}),
            research_service=FakeResearchService(),
        )

        response = service.process_text("chat-1", "user-1", 2, "broken")

        self.assertEqual(response.text, "❌ Could not parse")

    def test_process_text_returns_generic_success_with_link(self):
        service = ChatApplicationService(
            assistant_service=FakeAssistantService(
                {"success": True, "action": "created", "message": "Done", "event_link": "https://example.com/x"}
            ),
            research_service=FakeResearchService(),
        )

        response = service.process_text("chat-1", "user-1", 3, "create")

        self.assertEqual(response.parse_mode, "HTML")
        self.assertIn("https://example.com/x", response.text)

    def test_edit_pending_task_returns_task_specific_prompt(self):
        assistant = FakeAssistantService(
            {
                "success": True,
                "action": "confirm_task",
                "task": Task(
                    title="Pay bills",
                    due_time=datetime(2026, 3, 9, 18, 0),
                    duration_minutes=30,
                    description="Utilities",
                ),
                "message": "Confirm task",
            }
        )
        service = ChatApplicationService(assistant_service=assistant, research_service=FakeResearchService())
        response = service.process_text("chat-1", "user-1", 123, "pay bills")

        edit_response = service.edit_pending(response.pending_id)

        self.assertIn("Редактирование задачи", edit_response.text)
        self.assertIn("Pay bills", edit_response.text)
        self.assertEqual(edit_response.parse_mode, "Markdown")

    def test_confirm_pending_event_uses_assistant_service(self):
        event = CalendarEvent(title="Sync", start_time=datetime(2026, 3, 9, 18, 0))
        assistant = FakeAssistantService(
            {
                "success": True,
                "action": "confirm",
                "event": event,
                "message": "Confirm event",
            }
        )
        service = ChatApplicationService(assistant_service=assistant, research_service=FakeResearchService())
        response = service.process_text("chat-1", "user-1", 55, "sync tomorrow")

        confirm_response = service.confirm_pending(response.pending_id)

        self.assertEqual(len(assistant.confirmed_events), 1)
        self.assertEqual(confirm_response.parse_mode, "HTML")
        self.assertIn("https://example.com/event", confirm_response.text)

    def test_cancel_pending_removes_confirmation(self):
        event = CalendarEvent(title="Sync", start_time=datetime(2026, 3, 9, 18, 0))
        service = ChatApplicationService(
            assistant_service=FakeAssistantService(
                {"success": True, "action": "confirm", "event": event, "message": "Confirm event"}
            ),
            research_service=FakeResearchService(),
        )
        response = service.process_text("chat-1", "user-1", 56, "sync tomorrow")

        cancel_response = service.cancel_pending(response.pending_id)
        missing_response = service.confirm_pending(response.pending_id)

        self.assertEqual(cancel_response.text, "❌ Создание события отменено.")
        self.assertEqual(missing_response.text, "❌ Событие не найдено или уже обработано.")

    def test_multiple_pending_requests_in_same_session_are_isolated(self):
        first_event = CalendarEvent(title="Sync", start_time=datetime(2026, 3, 9, 18, 0))
        second_task = Task(title="Pay bills", due_time=datetime(2026, 3, 9, 19, 0))
        assistant = FakeAssistantService(
            results=[
                {"success": True, "action": "confirm", "event": first_event, "message": "Confirm event"},
                {"success": True, "action": "confirm_task", "task": second_task, "message": "Confirm task"},
            ]
        )
        service = ChatApplicationService(assistant_service=assistant, research_service=FakeResearchService())

        first = service.process_text("chat-1", "user-1", 10, "event")
        second = service.process_text("chat-1", "user-1", 11, "task")
        confirm_second = service.confirm_pending(second.pending_id)
        edit_first = service.edit_pending(first.pending_id)

        self.assertNotEqual(first.pending_id, second.pending_id)
        self.assertEqual(len(assistant.confirmed_tasks), 1)
        self.assertEqual(len(assistant.confirmed_events), 0)
        self.assertIn("Редактирование события", edit_first.text)
        self.assertEqual(confirm_second.text, "✅ Task created")

    def test_assistant_returned_research_action_routes_through_research_service(self):
        research = FakeResearchService()
        service = ChatApplicationService(
            assistant_service=FakeAssistantService(
                {"success": True, "action": "research", "original_query": "Тема", "mode": "followup"}
            ),
            research_service=research,
        )

        response = service.process_text("chat-1", "user-1", 8, "неважно")

        self.assertEqual(response.text, "research:followup:Тема")
        self.assertEqual(research.calls, [("chat-1", "Тема", "followup")])

    def test_research_requests_bypass_assistant_confirmation_flow(self):
        research = FakeResearchService()
        service = ChatApplicationService(
            assistant_service=FakeAssistantService(),
            research_service=research,
        )

        response = service.process_text("chat-1", "user-1", 7, "Исследуй рынок ИИ")

        self.assertEqual(response.text, "research:new:Исследуй рынок ИИ")
        self.assertEqual(research.calls, [("chat-1", "Исследуй рынок ИИ", "new")])

    def test_followup_research_request_bypasses_assistant_and_preserves_session_flow(self):
        research = FakeResearchService()
        service = ChatApplicationService(
            assistant_service=FakeAssistantService(),
            research_service=research,
        )

        first = service.process_text("chat-1", "user-1", 7, "Исследуй рынок ИИ")
        second = service.process_text("chat-1", "user-1", 8, "Подробнее про выводы")

        self.assertEqual(first.text, "research:new:Исследуй рынок ИИ")
        self.assertEqual(second.text, "research:followup:Подробнее про выводы")
        self.assertEqual(
            research.calls,
            [("chat-1", "Исследуй рынок ИИ", "new"), ("chat-1", "Подробнее про выводы", "followup")],
        )


if __name__ == "__main__":
    unittest.main()