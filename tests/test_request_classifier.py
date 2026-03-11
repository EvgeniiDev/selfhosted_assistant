from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from capability_registry import CapabilityRegistry
from intent_classifier import IntentClassifier
from llm_core.contracts import LLMResponse
from models import CalendarEvent, Note, ResearchRequest, Task
from request_classifier import RequestClassifier


class _FakeIntentClassifier:
    def __init__(self, result: str):
        self.result = result

    def classify_request(self, user_message: str) -> str:
        return self.result


class _FakeGateway:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        content = self.responses.pop(0) if self.responses else ""
        return LLMResponse(content=content, provider="fake", model_id="fake")


class _FakeNoteSkillService:
    def __init__(self, note: Note | None):
        self.note = note
        self.calls = []

    def create_note(self, user_message: str, current_time):
        self.calls.append((user_message, current_time))
        return self.note


class _FakeTaskSkillService:
    def __init__(self, task: Task | None):
        self.task = task
        self.calls = []

    def create_task(self, user_message: str, current_time_text: str):
        self.calls.append((user_message, current_time_text))
        return self.task


class _FakeCalendarEventSkillService:
    def __init__(self, event: CalendarEvent | None):
        self.event = event
        self.calls = []

    def create_calendar_event(self, user_message: str, current_time_text: str):
        self.calls.append((user_message, current_time_text))
        return self.event


class RequestClassifierTests(unittest.TestCase):
    def _build_registry(self, temp_dir: str, capabilities: dict, classification: dict | None = None) -> CapabilityRegistry:
        path = Path(temp_dir) / "capabilities.json"
        payload = {"capabilities": capabilities}
        if classification is not None:
            payload["classification"] = classification
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return CapabilityRegistry(config_path=path)

    def _classification_config(self, **overrides) -> dict:
        config = {
            "task_type": "classification",
            "system_prompt": "return only one label",
            "valid_types": ["calendar_event", "task", "note", "research", "list_notes", "unknown"],
            "default_intent": "note",
            "heuristics": {
                "list_notes": ["show notes"],
                "research": ["исследуй", "подробнее"],
                "task": ["напомни", "todo"],
                "calendar_event": ["созвон", "meeting"],
            },
            "datetime_keywords": ["завтра", "понедельник"],
        }
        config.update(overrides)
        return config

    def test_intent_classifier_uses_registry_heuristics_on_unknown_model_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = self._build_registry(temp_dir, {}, classification=self._classification_config())
            classifier = IntentClassifier(
                gateway=_FakeGateway(["unknown"]),
                capability_registry=registry,
            )

            result = classifier.classify_request("созвон завтра в 18:00")

            self.assertEqual(result, "calendar_event")

    def test_intent_classifier_uses_registry_default_intent_for_empty_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = self._build_registry(
                temp_dir,
                {},
                classification=self._classification_config(default_intent="note"),
            )
            classifier = IntentClassifier(
                gateway=_FakeGateway([""]),
                capability_registry=registry,
            )

            result = classifier.classify_request("")

            self.assertEqual(result, "note")

    def test_note_requests_use_skill_backed_path_when_configured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = self._build_registry(
                temp_dir,
                {
                    "note": {
                        "skill_name": "note-capture",
                        "task_type": "note",
                        "system_prompt": "note skill",
                        "text_only": True,
                        "allow_mcp_tools": False
                    },
                    "research": {
                        "skill_name": "research-pipeline",
                        "task_type": "research",
                        "system_prompt": "research skill",
                        "text_only": True,
                        "allow_mcp_tools": True
                    }
                },
            )

            skill_note = Note(title="Из skill", content="Текст", created_at="2026-03-09T23:00:00", tags=None)
            skill_service = _FakeNoteSkillService(skill_note)
            classifier = RequestClassifier(
                gateway=SimpleNamespace(),
                router=SimpleNamespace(get_active_provider=lambda: "fake"),
                capability_registry=registry,
                intent_classifier=_FakeIntentClassifier("note"),
                calendar_event_skill_service=_FakeCalendarEventSkillService(None),
                note_skill_service=skill_service,
                task_skill_service=_FakeTaskSkillService(None),
            )

            result = classifier.process_request("запиши: купить молоко")

            self.assertIsInstance(result, Note)
            self.assertEqual(result.title, "Из skill")
            self.assertEqual(len(skill_service.calls), 1)
            self.assertEqual(skill_service.calls[0][0], "запиши: купить молоко")

    def test_note_requests_fail_when_skill_capability_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = self._build_registry(
                temp_dir,
                {
                    "research": {
                        "skill_name": "research-pipeline",
                        "task_type": "research",
                        "system_prompt": "research skill",
                        "text_only": True,
                        "allow_mcp_tools": True
                    }
                },
            )

            skill_service = _FakeNoteSkillService(None)
            classifier = RequestClassifier(
                gateway=SimpleNamespace(),
                router=SimpleNamespace(get_active_provider=lambda: "fake"),
                capability_registry=registry,
                intent_classifier=_FakeIntentClassifier("note"),
                calendar_event_skill_service=_FakeCalendarEventSkillService(None),
                note_skill_service=skill_service,
                task_skill_service=_FakeTaskSkillService(None),
            )

            result = classifier.process_request("запиши: купить молоко")

            self.assertIsNone(result)
            self.assertEqual(len(skill_service.calls), 0)

    def test_task_requests_use_skill_backed_path_when_configured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = self._build_registry(
                temp_dir,
                {
                    "note": {
                        "skill_name": "note-capture",
                        "task_type": "note",
                        "system_prompt": "note skill",
                        "text_only": True,
                        "allow_mcp_tools": False
                    },
                    "task": {
                        "skill_name": "task-capture",
                        "task_type": "task",
                        "system_prompt": "task skill",
                        "text_only": True,
                        "allow_mcp_tools": False
                    },
                    "research": {
                        "skill_name": "research-pipeline",
                        "task_type": "research",
                        "system_prompt": "research skill",
                        "text_only": True,
                        "allow_mcp_tools": True
                    }
                },
            )

            task = Task(title="Pay bills", due_time="2026-03-10T18:00:00")
            classifier = RequestClassifier(
                gateway=SimpleNamespace(),
                router=SimpleNamespace(get_active_provider=lambda: "fake"),
                capability_registry=registry,
                intent_classifier=_FakeIntentClassifier("task"),
                calendar_event_skill_service=_FakeCalendarEventSkillService(None),
                note_skill_service=_FakeNoteSkillService(None),
                task_skill_service=_FakeTaskSkillService(task),
            )

            result = classifier.process_request("оплатить счета завтра в 18:00")

            self.assertIsInstance(result, Task)
            self.assertEqual(result.title, "Pay bills")

    def test_task_requests_fail_when_skill_capability_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = self._build_registry(
                temp_dir,
                {
                    "note": {
                        "skill_name": "note-capture",
                        "task_type": "note",
                        "system_prompt": "note skill",
                        "text_only": True,
                        "allow_mcp_tools": False
                    },
                    "research": {
                        "skill_name": "research-pipeline",
                        "task_type": "research",
                        "system_prompt": "research skill",
                        "text_only": True,
                        "allow_mcp_tools": True
                    }
                },
            )

            classifier = RequestClassifier(
                gateway=SimpleNamespace(),
                router=SimpleNamespace(get_active_provider=lambda: "fake"),
                capability_registry=registry,
                intent_classifier=_FakeIntentClassifier("task"),
                calendar_event_skill_service=_FakeCalendarEventSkillService(None),
                note_skill_service=_FakeNoteSkillService(None),
                task_skill_service=_FakeTaskSkillService(None),
            )

            result = classifier.process_request("оплатить счета завтра в 18:00")

            self.assertIsNone(result)

    def test_calendar_event_requests_use_skill_backed_path_when_configured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = self._build_registry(
                temp_dir,
                {
                    "calendar_event": {
                        "skill_name": "calendar-event-capture",
                        "task_type": "calendar_event",
                        "system_prompt": "calendar skill",
                        "text_only": True,
                        "allow_mcp_tools": False
                    },
                    "note": {
                        "skill_name": "note-capture",
                        "task_type": "note",
                        "system_prompt": "note skill",
                        "text_only": True,
                        "allow_mcp_tools": False
                    },
                    "task": {
                        "skill_name": "task-capture",
                        "task_type": "task",
                        "system_prompt": "task skill",
                        "text_only": True,
                        "allow_mcp_tools": False
                    },
                    "research": {
                        "skill_name": "research-pipeline",
                        "task_type": "research",
                        "system_prompt": "research skill",
                        "text_only": True,
                        "allow_mcp_tools": True
                    }
                },
            )

            event = CalendarEvent(title="Sync", start_time="2026-03-10T18:00:00")
            event_service = _FakeCalendarEventSkillService(event)
            classifier = RequestClassifier(
                gateway=SimpleNamespace(),
                router=SimpleNamespace(get_active_provider=lambda: "fake"),
                capability_registry=registry,
                intent_classifier=_FakeIntentClassifier("calendar_event"),
                calendar_event_skill_service=event_service,
                note_skill_service=_FakeNoteSkillService(None),
                task_skill_service=_FakeTaskSkillService(None),
            )

            result = classifier.process_request("созвон завтра в 18:00")

            self.assertIsInstance(result, CalendarEvent)
            self.assertEqual(result.title, "Sync")
            self.assertEqual(len(event_service.calls), 1)

    def test_calendar_event_requests_fail_when_skill_capability_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = self._build_registry(
                temp_dir,
                {
                    "note": {
                        "skill_name": "note-capture",
                        "task_type": "note",
                        "system_prompt": "note skill",
                        "text_only": True,
                        "allow_mcp_tools": False
                    },
                    "task": {
                        "skill_name": "task-capture",
                        "task_type": "task",
                        "system_prompt": "task skill",
                        "text_only": True,
                        "allow_mcp_tools": False
                    },
                    "research": {
                        "skill_name": "research-pipeline",
                        "task_type": "research",
                        "system_prompt": "research skill",
                        "text_only": True,
                        "allow_mcp_tools": True
                    }
                },
            )

            classifier = RequestClassifier(
                gateway=SimpleNamespace(),
                router=SimpleNamespace(get_active_provider=lambda: "fake"),
                capability_registry=registry,
                intent_classifier=_FakeIntentClassifier("calendar_event"),
                calendar_event_skill_service=_FakeCalendarEventSkillService(None),
                note_skill_service=_FakeNoteSkillService(None),
                task_skill_service=_FakeTaskSkillService(None),
            )

            result = classifier.process_request("созвон завтра в 18:00")

            self.assertIsNone(result)

    def test_research_requests_still_return_research_sentinel(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = self._build_registry(
                temp_dir,
                {
                    "research": {
                        "skill_name": "research-pipeline",
                        "task_type": "research",
                        "system_prompt": "research skill",
                        "text_only": True,
                        "allow_mcp_tools": True
                    }
                },
            )

            classifier = RequestClassifier(
                gateway=SimpleNamespace(),
                router=SimpleNamespace(get_active_provider=lambda: "fake"),
                capability_registry=registry,
                intent_classifier=_FakeIntentClassifier("research"),
                calendar_event_skill_service=_FakeCalendarEventSkillService(None),
                note_skill_service=_FakeNoteSkillService(None),
                task_skill_service=_FakeTaskSkillService(None),
            )

            result = classifier.process_request("исследуй рынок ИИ")

            self.assertIsInstance(result, ResearchRequest)
            self.assertEqual(result.original_query, "исследуй рынок ИИ")