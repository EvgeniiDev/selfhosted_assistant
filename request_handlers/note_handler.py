from typing import Optional
from datetime import datetime
from models import Note
from .base_handler import BaseRequestHandler


class NoteHandler(BaseRequestHandler):
    
    PROMPT = """
Ты — форматтер заметок. Пользователь хочет сохранить заметку. Сформируй ответ строго в виде JSON и ничего больше.

Верни ровно такую JSON-структуру:
{
  "type": "note",
  "data": {
    "title": "string",
    "content": "string",
    "created_at": "YYYY-MM-DDTHH:MM:SS",
    "tags": ["string", "string"] or null
  }
}

Правила для "content":
1) Не изменяй смысл, факты, порядок и объём информации. Ничего не добавляй и не удаляй.
2) Исправляй только:
   - заглавные буквы в начале предложений и имен собственных,
   - знаки препинания,
   - опечатки и орфографические ошибки в русских словах.
3) Не перефразируй, не сокращай и не расширяй формулировки.
4) Сохраняй исходные абзацы, переносы строк, списки, числа, даты, ссылки, эмодзи и форматирование (кроме исправлений из п.2).
5) Фрагменты на других языках не переводить; менять только пунктуацию вокруг них при необходимости.
6) Нормализуй пробелы: один пробел между словами, без пробелов перед знаками препинания, ставь пробел после знаков, где это требуется.

Правила для "title":
- Короткий и описательный (3–7 слов).
- Не содержит новых фактов, только отражает суть заметки.

Правила для "tags":
- Извлекай релевантные теги при наличии (не более 3); иначе null.
- Теги — короткие существительные в нижнем регистре, без символов "#", без повторов.

Правила для "created_at":
- Используй текущие локальные дату и время в формате YYYY-MM-DDTHH:MM:SS.

Требования к ответу:
- Верни ТОЛЬКО JSON, в одну строку без переносов, без текста, пояснений, кода или бэктиков.
- Компактный JSON: без лишних пробелов между элементами, без экранирования специальных символов, без лишних запятых.
"""
    
    def get_prompt(self) -> str:
        return self.PROMPT
    
    def get_handler_name(self) -> str:
        return "NoteHandler"

    def get_task_type(self) -> str:
        return "note"
    
    def parse_response(self, response_content: str, **kwargs) -> Optional[Note]:
        parsed_data = self.extract_json_from_response(response_content)
        
        if parsed_data and parsed_data.get('type') == 'note':
            try:
                return Note(**parsed_data['data'])
            except Exception as e:
                from logger import calendar_logger
                calendar_logger.log_error(e, f"{self.get_handler_name()}.parse_response - Note creation")
                return None
        
        return None
    
    def create_note(self, enhanced_message: str, current_time: datetime) -> Optional[Note]:
        return self.process(enhanced_message, False, current_time=current_time)
