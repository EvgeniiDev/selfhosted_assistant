# Tests Index

Каталог с unit/integration тестами для основного application и LLM flow.

## Файлы
- `test_chat_application_service.py` - orchestration логика приложения и чатов.
- `test_copilot_provider_sessions.py` - устойчивость Copilot provider sessions и timeout handling.
- `test_non_telegram_session_scenarios.py` - сценарии сессий вне Telegram transport.
- `test_request_classifier.py` - capability routing, intent classification и skill-backed extraction flow.
- `test_real_copilot_research_integration.py` - реальная интеграция с Copilot runtime для research.
- `test_research_service.py` - research flow, контекст и follow-up логика.
- `test_session_routing.py` - выбор активной research-сессии, reset и переключение.
- `test_voice_input_service.py` - voice/audio input pipeline.

## Как пользоваться
- Для быстрых локальных проверок запускай `scripts/run_tests.py fast`.
- Реальные runtime-проверки отделены в `test_real_copilot_research_integration.py` и suite `real-copilot`.

## Что здесь не искать
- Telegram end-to-end сценарии с реальным ботом здесь покрыты ограниченно; основная ценность каталога в service-level и provider-level проверках.