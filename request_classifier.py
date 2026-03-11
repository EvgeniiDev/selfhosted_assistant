from typing import Optional, Union
from datetime import datetime
from calendar_event_skill_service import CalendarEventSkillService
from capability_registry import CapabilityRegistry
from capability_router import CapabilityRouter
from logger import calendar_logger
from models import CalendarEvent, Note, Task, ResearchRequest, ListNotesRequest
from integrations.copilot_sdk import CopilotSDKProvider
from llm_core import LLMGateway, LLMRouter
from note_skill_service import NoteSkillService
from task_skill_service import TaskSkillService
from intent_classifier import IntentClassifier

class RequestClassifier:
    def __init__(
        self,
        gateway: LLMGateway | None = None,
        router: LLMRouter | None = None,
        capability_registry: CapabilityRegistry | None = None,
        intent_classifier: IntentClassifier | None = None,
        calendar_event_skill_service: CalendarEventSkillService | None = None,
        note_skill_service: NoteSkillService | None = None,
        task_skill_service: TaskSkillService | None = None,
    ):
        self.router = router or LLMRouter()
        self.gateway = gateway or LLMGateway(
            router=self.router,
            providers={"copilot": CopilotSDKProvider()},
        )
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.capability_router = CapabilityRouter(self.capability_registry)

        self.intent_classifier = intent_classifier or IntentClassifier(
            gateway=self.gateway,
            capability_registry=self.capability_registry,
        )
        self.calendar_event_skill_service = calendar_event_skill_service
        if self.calendar_event_skill_service is None and self.capability_router.is_skill_backed("calendar_event"):
            self.calendar_event_skill_service = CalendarEventSkillService(
                gateway=self.gateway,
                capability_registry=self.capability_registry,
            )

        self.note_skill_service = note_skill_service
        if self.note_skill_service is None and self.capability_router.is_skill_backed("note"):
            self.note_skill_service = NoteSkillService(
                gateway=self.gateway,
                capability_registry=self.capability_registry,
            )

        self.task_skill_service = task_skill_service
        if self.task_skill_service is None and self.capability_router.is_skill_backed("task"):
            self.task_skill_service = TaskSkillService(
                gateway=self.gateway,
                capability_registry=self.capability_registry,
            )
        
        calendar_logger.info('RequestClassifier initialized with capability registry routing')
        calendar_logger.info(f"Active LLM provider: {self.router.get_active_provider()}")

    def process_request(self, user_message: str) -> Optional[Union[CalendarEvent, Note, Task, ResearchRequest, ListNotesRequest]]:
        current_time = datetime.now()
        current_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S (%A)")
        
        try:
            classification = self.intent_classifier.classify_request(user_message)
            
            match classification:
                case "calendar_event":
                    if not self.capability_router.is_skill_backed("calendar_event"):
                        calendar_logger.warning("Calendar event capability is not configured in capability registry")
                        return None
                    return self.calendar_event_skill_service.create_calendar_event(user_message, current_time_str)
                case "task":
                    if not self.capability_router.is_skill_backed("task"):
                        calendar_logger.warning("Task capability is not configured in capability registry")
                        return None
                    return self.task_skill_service.create_task(user_message, current_time_str)
                case "note":
                    if not self.capability_router.is_skill_backed("note"):
                        calendar_logger.warning("Note capability is not configured in capability registry")
                        return None
                    return self.note_skill_service.create_note(user_message, current_time)
                case "research":
                    if not self.capability_router.is_skill_backed("research"):
                        calendar_logger.warning("Research capability is not configured in capability registry")
                        return None
                    return ResearchRequest(original_query=user_message)
                case "list_notes":
                    return ListNotesRequest()
                case _:
                    calendar_logger.log_error(
                        Exception(f"Unexpected classification: {classification}"),
                        "request_classifier.process_request - classification"
                    )
                    return None
                    
        except Exception as e:
            calendar_logger.log_error(e, "request_classifier.process_request - General exception")
            return None
