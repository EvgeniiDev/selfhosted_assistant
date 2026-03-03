from typing import Optional
from models import CalendarEvent
from .base_handler import BaseRequestHandler


class CalendarEventHandler(BaseRequestHandler):
    
    PROMPT = """
You are a calendar event extractor. The user wants to create a calendar event. Extract event details and return ONLY a JSON response.

Return exactly this JSON structure:
{
  "type": "calendar_event",
  "data": {
    "title": "string",
    "description": "string or null",
    "start_time": "YYYY-MM-DDTHH:MM:SS",
    "end_time": "YYYY-MM-DDTHH:MM:SS or null",
    "duration_minutes": "number or null",
    "recurrence": "string or null"
  }
}

## Rules:
1. Assume all times are in the user's local time zone
2. If **end time** is specified → fill `end_time`, set `duration_minutes` = null
3. If **duration** is specified → fill `duration_minutes`, set `end_time` = null
4. If **neither** is specified → set `duration_minutes` = 60, `end_time` = null

## Recurrence values:
- `null` - one-time event
- `"Daily"` - every day
- `"Weekly on [day of week]"` - weekly
- `"Monthly on the first [day of week]"` - monthly
- `"Annually on [month day]"` - yearly
- `"Every weekday (Monday to Friday)"` - workdays

For dates without year, assume current year or next occurrence if date has passed.
"""
    
    def get_prompt(self) -> str:
        return self.PROMPT
    
    def get_handler_name(self) -> str:
        return "CalendarEventHandler"

    def get_task_type(self) -> str:
        return "calendar_event"
    
    def parse_response(self, response_content: str, **kwargs) -> Optional[CalendarEvent]:
        parsed_data = self.extract_json_from_response(response_content)
        
        if parsed_data and parsed_data.get('type') == 'calendar_event':
            try:
                return CalendarEvent(**parsed_data['data'])
            except Exception as e:
                from logger import calendar_logger
                calendar_logger.log_error(e, f"{self.get_handler_name()}.parse_response - CalendarEvent creation")
                return None
        
        return None
    
    def create_calendar_event(self, enhanced_message: str) -> Optional[CalendarEvent]:
        return self.process(enhanced_message, False)
