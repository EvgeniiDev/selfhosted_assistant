"""
Главный роутер для выбора модели на основе приватности
"""

import json
from typing import Optional, Dict
from logger import calendar_logger
from llm_inference.local_provider import LocalProvider
from llm_inference.openrouter_provider import OpenRouterProvider
from llm_inference.privacy_detector import PrivacyDetector


class ModelRouter:
    """Простой роутер для выбора между локальной и облачной моделью"""
    
    def __init__(self, config_path: str = "model_config.json"):
        self.config = self._load_config(config_path)
        
        # Инициализируем провайдеры
        self.local_provider = LocalProvider()
        self.openrouter_provider = OpenRouterProvider()
        self.privacy_detector = PrivacyDetector()
        
        calendar_logger.info("ModelRouter initialized")
    
    def _load_config(self, config_path: str) -> Dict:
        """Загрузка конфигурации моделей"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            calendar_logger.log_error(e, f"Error loading config {config_path}")
            return {"models": []}
    
    def _get_public_models(self) -> list[Dict]:
        """Получение списка публичных моделей, отсортированных по приоритету"""
        models = self.config.get("models", [])
        public_models = []
        
        # Фильтруем публичные модели
        for model in models:
            if (model.get("enabled", True) and 
                model.get("provider") == "openrouter" and
                "public_chat" in model.get("task_types", [])):
                public_models.append(model)
        
        if not public_models:
            return []
        
        # Сортируем по приоритету (бесплатные модели имеют приоритет 1)
        public_models.sort(key=lambda x: x.get("priority", 99))

        return public_models
    
    def _get_local_model(self) -> Optional[Dict]:
        """Получение локальной модели"""
        models = self.config.get("models", [])
        
        for model in models:
            if (model.get("enabled", True) and 
                model.get("provider") == "local"):
                return model
        
        return None
    
    def generate(self, text: str, system_prompt: str = None, is_private: Optional[bool] = None) -> Optional[str]:
        """
        Генерация ответа с автоматическим выбором модели
        
        Args:
            text: Текст запроса
            system_prompt: Системный промпт (опционально)
            is_private: Явное указание приватности (опционально)
            
        Returns:
            Ответ модели или None в случае ошибки
        """
        # Определяем приватность
        if is_private is None:
            is_private = self.privacy_detector.is_private(text)
        
        # Подготавливаем сообщения
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": text})
        
        if is_private:
            # Используем локальную модель для приватных запросов
            calendar_logger.info("Using LOCAL model for private request")
            
            if not self.local_provider.is_available():
                calendar_logger.warning("Local model not available")
                return None
            
            model = self._get_local_model()
            if not model:
                calendar_logger.warning("No local model configured")
                return None
            
            return self.local_provider.generate(messages, model.get("model_id", "local-model"))
        
        else:
            # Используем публичную модель для публичных запросов
            calendar_logger.info("Using PUBLIC model for public request")
            
            if not self.openrouter_provider.is_available():
                calendar_logger.warning("OpenRouter not available")
                return None
            
            public_models = self._get_public_models()
            if not public_models:
                calendar_logger.warning("No public model configured")
                return None

            model_ids = [model["model_id"] for model in public_models]
            calendar_logger.info(
                f"Selected public models (fallback chain): {', '.join(model_ids)}"
            )
            return self.openrouter_provider.generate(messages, model_ids=model_ids)
    
    def get_status(self) -> Dict:
        """Получение статуса провайдеров"""
        return {
            "local_available": self.local_provider.is_available(),
            "openrouter_available": self.openrouter_provider.is_available(),
            "models_count": len(self.config.get("models", []))
        }
