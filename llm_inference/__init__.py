"""
LLM Inference Package
Модуль для работы с различными LLM моделями
"""

from llm_inference.local_provider import LocalProvider
from llm_inference.privacy_detector import PrivacyDetector

__all__ = ['LocalProvider', 'PrivacyDetector']
