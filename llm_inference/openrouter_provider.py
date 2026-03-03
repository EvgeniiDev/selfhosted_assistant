"""
Провайдер для OpenRouter API
"""

import os
import requests
from typing import Optional
from logger import calendar_logger


class OpenRouterProvider:
    """провайдер для OpenRouter"""
    
    def __init__(self, api_url: str = "https://openrouter.ai/api/v1/chat/completions"):
        self.api_url = api_url
        self.api_key = os.getenv('OPEN_ROUTER_API_KEY')
        
    def is_available(self) -> bool:
        """Проверка доступности OpenRouter"""
        return bool(self.api_key)
    
    def generate(self, messages: list, model_id: str = None, model_ids: list[str] = None) -> Optional[str]:
        """Генерация ответа от OpenRouter с fallback по провайдерам и моделям"""
        if not self.api_key:
            calendar_logger.warning("OpenRouter API key not found")
            return None

        if not model_id and not model_ids:
            calendar_logger.warning("OpenRouter model_id/model_ids not provided")
            return None

        payload = {
            "messages": messages,
            "provider": {
                "allow_fallbacks": True,
                "sort": {
                    "by": "throughput",
                    "partition": "none"
                }
            }
        }

        if model_ids and len(model_ids) > 1:
            payload["models"] = model_ids
            payload["route"] = "fallback"
        else:
            payload["model"] = model_id or model_ids[0]
            
        try:
            response = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=120
            )
            
            if response.status_code == 200:
                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0]["message"]["content"].strip()
                    used_model = data.get("model", model_id or (model_ids[0] if model_ids else "unknown"))
                    calendar_logger.info(f"OpenRouter response received: {used_model}")
                    return content
            
            calendar_logger.warning(f"OpenRouter failed: {response.status_code} - {response.text}")
            return None
            
        except Exception as e:
            model_label = model_id or (", ".join(model_ids) if model_ids else "unknown")
            calendar_logger.log_error(e, f"OpenRouterProvider.generate - {model_label}")
            return None
