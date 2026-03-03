from typing import Optional
from models import Task
from .base_handler import BaseRequestHandler


class TaskHandler(BaseRequestHandler):

    PROMPT = """
You are a task extractor. The user wants to create a task/reminder that should be added to calendar as a task or event.

Return exactly this JSON structure:
{
  "type": "task",
  "data": {
    "title": "string",
    "description": "string or null",
    "due_time": "YYYY-MM-DDTHH:MM:SS or null",
    "duration_minutes": "number or null",
    "recurrence": "string or null"
  }
}

Rules:
1. If due_time is provided use it as start_time. If duration provided, treat as estimated duration.
2. If neither due_time nor duration provided, set due_time to null.
"""

    def get_prompt(self) -> str:
        return self.PROMPT

    def get_handler_name(self) -> str:
        return "TaskHandler"

    def get_task_type(self) -> str:
        return "task"

    def parse_response(self, response_content: str, **kwargs) -> Optional[Task]:
        parsed_data = self.extract_json_from_response(response_content)

        if parsed_data and parsed_data.get('type') == 'task':
            try:
                return Task(**parsed_data['data'])
            except Exception:
                from logger import calendar_logger
                calendar_logger.log_error(Exception('Task parsing error'), f"{self.get_handler_name()}.parse_response - Task creation")
                return None

        return None

    def create_task(self, enhanced_message: str) -> Optional[Task]:
        return self.process(enhanced_message, False)
