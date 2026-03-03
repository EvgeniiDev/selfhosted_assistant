import logging
from datetime import datetime
from typing import Any, Dict, Optional
from pathlib import Path


class CalendarLogger:
    def __init__(self, log_file: str = "calendar_assistant.log"):
        """Инициализация логгера для календарного ассистента"""
        self.log_file = Path(log_file)
        
        # Создаем директорию для логов если она не существует
        self.log_file.parent.mkdir(exist_ok=True)
        
        # Настройка логгера
        self.logger = logging.getLogger('calendar_assistant')
        self.logger.setLevel(logging.INFO)
        # Отключаем распространение сообщений к корневому логгеру,
        # чтобы избежать дублирования в консоли при наличии root-хендлеров
        self.logger.propagate = False
        
        # Удаляем старые хендлеры если они есть
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
        
        # Настройка форматтера
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Файловый хендлер
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        
        # Консольный хендлер
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def log_user_request(self, user_id: Optional[str], username: Optional[str], message: str):
        """Логирование запроса от пользователя из Telegram"""
        timestamp = datetime.now().isoformat()
        log_msg = f"USER_REQUEST | User: {username} (ID: {user_id}) | Message: {message} | Time: {timestamp}"
        self.logger.info(log_msg)
    
    def log_llm_prompt(self, prompt: str, system_prompt: str):
        """Логирование промта, отправленного в LLM"""
        timestamp = datetime.now().isoformat()
        log_msg = f"LLM_PROMPT | System: {system_prompt} | User: {prompt} | Time: {timestamp}"
        self.logger.info(log_msg)
    
    def log_llm_response(self, response: str, parsed_data: Optional[Dict[str, Any]] = None):
        """Логирование ответа от LLM"""
        timestamp = datetime.now().isoformat()
        parsed_str = str(parsed_data) if parsed_data else "None"
        log_msg = f"LLM_RESPONSE | Raw: {response} | Parsed: {parsed_str} | Time: {timestamp}"
        self.logger.info(log_msg)
    
    def log_calendar_request(self, event_data: Dict[str, Any]):
        """Логирование запроса к Google Calendar"""
        timestamp = datetime.now().isoformat()
        log_msg = f"CALENDAR_REQUEST | Event: {str(event_data)} | Time: {timestamp}"
        self.logger.info(log_msg)
    
    def log_calendar_response(self, success: bool, response_data: Dict[str, Any]):
        """Логирование ответа от Google Calendar"""
        timestamp = datetime.now().isoformat()
        log_msg = f"CALENDAR_RESPONSE | Success: {success} | Data: {str(response_data)} | Time: {timestamp}"
        self.logger.info(log_msg)
    
    def log_error(self, error: Exception, context: str = ""):
        """Логирование ошибок с трассировкой стека"""
        timestamp = datetime.now().isoformat()
        context_str = f" | Context: {context}" if context else ""
        log_msg = f"ERROR | Type: {type(error).__name__} | Message: {str(error)}{context_str} | Time: {timestamp}"
        # Используем exception, чтобы записать traceback. Вызывать из блока except.
        self.logger.exception(log_msg)

    def log_provider_selection(self, provider: str, model: str, route_reason: str, task_type: str):
        """Логирование маршрутизации на провайдера/модель."""
        timestamp = datetime.now().isoformat()
        log_msg = (
            f"LLM_ROUTE | Provider: {provider} | Model: {model} | "
            f"Reason: {route_reason} | TaskType: {task_type} | Time: {timestamp}"
        )
        self.logger.info(log_msg)

    def log_fallback(self, from_provider: str, to_provider: str, reason: str):
        """Логирование fallback между провайдерами."""
        timestamp = datetime.now().isoformat()
        log_msg = (
            f"LLM_FALLBACK | From: {from_provider} | To: {to_provider} | "
            f"Reason: {reason} | Time: {timestamp}"
        )
        self.logger.warning(log_msg)

    def log_policy_decision(self, policy_code: str, allowed: bool, reason: str, details: Dict[str, Any]):
        """Логирование решений policy-слоя."""
        timestamp = datetime.now().isoformat()
        log_msg = (
            f"LLM_POLICY | Code: {policy_code} | Allowed: {allowed} | "
            f"Reason: {reason} | Details: {details} | Time: {timestamp}"
        )
        self.logger.info(log_msg)

    def log_usage(self, usage: Dict[str, Any], trace: Dict[str, Any]):
        """Логирование usage/trace данных запроса."""
        timestamp = datetime.now().isoformat()
        log_msg = f"LLM_USAGE | Usage: {usage} | Trace: {trace} | Time: {timestamp}"
        self.logger.info(log_msg)
    
    def info(self, message: str):
        """Общее логирование информационных сообщений"""
        self.logger.info(message)
    
    def warning(self, message: str):
        """Логирование предупреждений"""
        self.logger.warning(message)
    
    def error(self, message: str):
        """Логирование ошибок (простой формат)"""
        self.logger.error(message)


# Глобальный экземпляр логгера
calendar_logger = CalendarLogger()
