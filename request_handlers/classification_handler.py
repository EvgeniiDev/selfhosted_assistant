from typing import Optional
import re
from logger import calendar_logger
from .base_handler import BaseRequestHandler


class ClassificationHandler(BaseRequestHandler):
    
    PROMPT = """
Сlassify text into one of these categories:

- **calendar_event**: mentions specific time, date, meetings, appointments, reminders with time constraints
- **note**: general information to remember, ideas, thoughts, lists, anything without specific time
- **task**: short task/reminder that the user wants to schedule or be reminded about (could have due date/time)
- **unknown**: unclear or ambiguous requests

Respond with ONLY one word: calendar_event, task, note, or unknown
"""
    
    def get_prompt(self) -> str:
        return self.PROMPT
    
    def get_handler_name(self) -> str:
        return "ClassificationHandler"

    def get_task_type(self) -> str:
        return "classification"
    
    def parse_response(self, response_content: str, **kwargs) -> Optional[str]:
        if not response_content:
            return None
        
        classification = response_content.strip().lower()
        valid_types = {"calendar_event", "note", "task", "unknown"}
        if classification in valid_types:
            calendar_logger.info(f"Request classified as: {classification}")
            return classification
        else:
            calendar_logger.warning(f"Invalid classification received: {classification}")
            return "unknown"
    
    def classify_request(self, user_message: str) -> str:
        try:
            classification = self.process(user_message, True)
            if classification:
                return classification

            fallback = self._heuristic_classification(user_message)
            calendar_logger.warning(f"ClassificationHandler: heuristic fallback used -> {fallback}")
            return fallback
            
        except Exception as e:
            calendar_logger.log_error(e, f"{self.get_handler_name()}.classify_request")
            return self._heuristic_classification(user_message)

    def _heuristic_classification(self, user_message: str) -> str:
        text = (user_message or "").strip().lower()
        if not text:
            return "unknown"

        task_keywords = (
            "напомни", "сделать", "сделай", "задача", "todo", "to-do", "дедлайн", "нужно"
        )
        calendar_keywords = (
            "встреч", "созвон", "митинг", "календар", "событи", "appointment", "meeting"
        )

        has_datetime_hint = bool(
            re.search(r"\b\d{1,2}:\d{2}\b", text)
            or re.search(r"\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b", text)
            or any(word in text for word in (
                "сегодня", "завтра", "послезавтра", "понедельник", "вторник", "сред", "четверг", "пятниц", "суббот", "воскрес",
                "январ", "феврал", "март", "апрел", "май", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"
            ))
        )

        if any(keyword in text for keyword in task_keywords):
            return "task"

        if any(keyword in text for keyword in calendar_keywords) and has_datetime_hint:
            return "calendar_event"

        return "note"
