# Local Inference Index

Каталог для локальных inference-компонентов и privacy-проверок.

## Файлы
- `local_provider.py` - заготовка или локальный provider для off-cloud inference сценариев.
- `privacy_detector.py` - вспомогательная логика для проверки приватности/чувствительных данных.
- `__init__.py` - пакетный маркер.

## Практический смысл
- Это не основной путь текущего production research flow.
- Папка важна, если проект будет усиливать local-first обработку или pre-filtering перед внешним LLM.