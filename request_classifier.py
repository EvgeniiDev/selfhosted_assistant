from typing import Optional, Union
from datetime import datetime
from logger import calendar_logger
from models import CalendarEvent, Note, Task
from integrations.copilot_sdk import CopilotSDKProvider
from integrations.openrouter import OpenRouterStandbyProvider
from llm_core import LLMGateway, LLMRouter
from request_handlers import (
    ClassificationHandler,
    CalendarEventHandler, 
    NoteHandler,
    TaskHandler
)

class RequestClassifier:
    def __init__(self):
        self.router = LLMRouter()
        self.gateway = LLMGateway(
            router=self.router,
            providers={
                "copilot": CopilotSDKProvider(),
                "openrouter": OpenRouterStandbyProvider(),
            },
        )
        
        self.classification_handler = ClassificationHandler(self.gateway)
        self.calendar_handler = CalendarEventHandler(self.gateway)
        self.note_handler = NoteHandler(self.gateway)
        self.task_handler = TaskHandler(self.gateway)
        
        calendar_logger.info('RequestClassifier initialized with notes support')
        calendar_logger.info(f"Active LLM provider: {self.router.get_active_provider()}")

    def process_request(self, user_message: str) -> Optional[Union[CalendarEvent, Note, Task]]:
        current_time = datetime.now()
        current_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S (%A)")
        
        try:
            classification = self.classification_handler.classify_request(user_message)
            
            if classification == "unknown":
                calendar_logger.warning(f"Unknown request type for: {user_message} request_classifier.classify - unknown type")
                classification = "note"
            
            enhanced_message = f"""
            ## Input Data
            - Current date: {current_time_str}
            - User query: {user_message}
            """
            
            match classification:
                case "calendar_event":
                    return self.calendar_handler.create_calendar_event(enhanced_message)
                case "task":
                    return self.task_handler.create_task(enhanced_message)
                case "note":
                    note = self.note_handler.create_note(enhanced_message, current_time)
                    if note:
                        return note
                    calendar_logger.warning("NoteHandler unavailable; using deterministic note fallback")
                    return self._build_fallback_note(user_message, current_time)
                case _:
                    calendar_logger.log_error(
                        Exception(f"Unexpected classification: {classification}"),
                        "request_classifier.process_request - classification"
                    )
                    return None
                    
        except Exception as e:
            calendar_logger.log_error(e, "request_classifier.process_request - General exception")
            return None

    def _build_fallback_note(self, user_message: str, current_time: datetime) -> Note:
        text = (user_message or "").strip()
        if not text:
            text = "Пустая заметка"

        words = text.replace("\n", " ").split()
        title = " ".join(words[:7]).strip()
        if len(words) > 7:
            title = f"{title}..."
        if not title:
            title = "Заметка"

        return Note(
            title=title,
            content=text,
            created_at=current_time.strftime("%Y-%m-%dT%H:%M:%S"),
            tags=None,
        )
