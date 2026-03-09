from typing import Optional
import re
from logger import calendar_logger
from .base_handler import BaseRequestHandler


class ClassificationHandler(BaseRequestHandler):
    
    PROMPT = """Classify the input text into exactly one category. Output ONLY the category word — no punctuation, no explanation, no other text.

Categories:
- calendar_event: mentions specific time, date, meetings, appointments, reminders with time constraints
- note: general information to remember, ideas, thoughts, lists, anything without specific time
- task: short task/reminder that the user wants to schedule or be reminded about (could have due date/time)
- research: user asks to investigate a topic, gather facts, compare sources, or perform a deep dive
- list_notes: user wants to view, list, browse, or retrieve their previously saved notes
- unknown: unclear or ambiguous requests

Output: one of these exact words: calendar_event, task, note, research, list_notes, unknown"""
    
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
        valid_types = {"calendar_event", "note", "task", "research", "list_notes", "unknown"}
        if classification in valid_types:
            calendar_logger.info(f"Request classified as: {classification}")
            return classification
        else:
            calendar_logger.warning(f"Invalid classification received: {classification}")
            return None
    
    def classify_request(self, user_message: str) -> str:
        try:
            classification = self.process(user_message, True)
            if classification and classification != "unknown":
                return classification

            fallback = self._heuristic_classification(user_message)
            if classification == "unknown":
                calendar_logger.warning(
                    f"ClassificationHandler: model returned 'unknown', heuristic override -> {fallback}"
                )
            else:
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
        research_keywords = (
            "исследуй",
            "найди информацию",
            "проведи исследование",
            "deep dive",
            "investigate",
            "research",
            "подробнее",
            "раскрой",
            "уточни",
            "пункт",
            "follow-up",
            "follow up",
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

        list_notes_keywords = (
            "мои заметки", "покажи заметки", "список заметок", "все заметки",
            "my notes", "show notes", "list notes", "get notes",
        )

        if any(keyword in text for keyword in list_notes_keywords):
            return "list_notes"

        if any(keyword in text for keyword in research_keywords):
            return "research"

        if any(keyword in text for keyword in task_keywords):
            return "task"

        if any(keyword in text for keyword in calendar_keywords) and has_datetime_hint:
            return "calendar_event"

        return "note"
