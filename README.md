# Self-Hosted Telegram Assistant (Google Calendar + Tasks + Notes + Voice)

Ассистент для Telegram, который понимает естественный язык и умеет:

- создавать события в Google Calendar (с подтверждением),
- создавать задачи в Google Tasks,
- сохранять заметки,
- обрабатывать голосовые сообщения и аудиофайлы (mp3/wav) через GigaAM.

LLM-часть работает через роутер моделей:

- локальная модель (LM Studio) — для приватных запросов,
- OpenRouter — для публичных запросов (опционально).

## Что сейчас поддерживается

- Автоклассификация запроса: `calendar_event`, `task`, `note`, `unknown`
- Подтверждение перед созданием события/задачи в Telegram
- Создание recurring-событий (RRULE для базовых сценариев)
- Ограничение доступа к боту через `TELEGRAM_ALLOWED_USERS`
- Полное логирование запросов/ответов/ошибок в `calendar_assistant.log`
- Распознавание голосовых и аудиофайлов (`mp3`/`wav`) через `gigaam` (без локального вендоринга исходников)

## Главные зависимости

Основные пакеты из `requirements.txt`:

- `python-telegram-bot==22.3` — Telegram Bot API
- `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib` — Google Calendar/Tasks API + OAuth
- `pydantic==2.11.7` — модели данных (`CalendarEvent`, `Task`, `Note`)
- `python-dateutil` — разбор дат/времени из LLM-ответов
- `requests` — HTTP-клиент для LM Studio/OpenRouter
- `python-dotenv` — загрузка `.env`
- `ffmpeg-python`, `pydub` — аудио-пайплайн
- `gigaam[longform]` (из GitHub) — ASR для голосовых сообщений

Важно:

- Для голоса нужен установленный `ffmpeg` в системе.
- Зависимости `torch/torchaudio` подтягиваются через `gigaam[longform]`.

## Быстрый старт

### 1) Подготовка окружения

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Настройка Telegram

1. Создайте бота через `@BotFather`
2. Получите `TELEGRAM_BOT_TOKEN`

### 3) Настройка Google API

1. В Google Cloud включите **Google Calendar API** и **Google Tasks API**
2. Создайте OAuth Client ID (Desktop)
3. Положите `credentials.json` в корень проекта (или укажите путь через `GOOGLE_CREDENTIALS_PATH`)
4. При первом запуске произойдет OAuth-авторизация и в консоли будет показан `GOOGLE_OAUTH_TOKEN_V2` (и legacy `GOOGLE_OAUTH_TOKEN`)

### 4) Настройка LLM

#### Локальная модель (рекомендуется)

1. Установите [LM Studio](https://lmstudio.ai/)
2. Запустите Local Server на `http://127.0.0.1:1234`
3. Загрузите инструкционную модель (например, Qwen/Gemma/Mistral)

#### OpenRouter (опционально)

Укажите `OPEN_ROUTER_API_KEY`, если хотите использовать облачную модель для публичных запросов.

### 5) Переменные окружения

Рекомендуется хранить их в `.env` (его читает `python-dotenv` при запуске бота).

Минимально необходимые:

- `TELEGRAM_BOT_TOKEN`
- `GOOGLE_CREDENTIALS_PATH` (или `credentials.json` в корне)
- `GOOGLE_OAUTH_TOKEN_V2` (после первой авторизации)

Полный список используемых переменных:

- `TELEGRAM_BOT_TOKEN` — токен Telegram-бота
- `TELEGRAM_ALLOWED_USERS` — whitelist пользователей (`username`/`id` через запятую)
- `GOOGLE_CREDENTIALS_PATH` — путь к OAuth credentials
- `GOOGLE_OAUTH_TOKEN_V2` — основной OAuth token v2 (JSON с `client_id`, `client_secret`, `refresh_token`, `token_uri`)
- `GOOGLE_OAUTH_TOKEN` — JSON-строка токена OAuth
- `GOOGLE_OAUTH_CLIENT_CONFIG` — OAuth client config JSON (альтернатива `credentials.json` для интерактивной авторизации)
- `GOOGLE_TASKLIST_ID` — id списка задач (иначе используется `@default`)
- `TIMEZONE` — часовой пояс для событий/задач (по умолчанию `Europe/Moscow`)
- `OPEN_ROUTER_API_KEY` — ключ OpenRouter
- `GIGAAM_MODEL_NAME` — модель ASR (по умолчанию `v3_e2e_rnnt`)

Примечание: файл `.env.example` содержит также исторические поля (`MODEL_PATH`, `DEFAULT_TIMEZONE`), которые текущим кодом напрямую не используются.

### OAuth только через переменные окружения

Можно работать без `credentials.json` на сервере:

- В runtime достаточно `GOOGLE_OAUTH_TOKEN_V2` (предпочтительно).
- Для одноразового получения/обновления токена можно задать `GOOGLE_OAUTH_CLIENT_CONFIG` (JSON OAuth client) и пройти интерактивную авторизацию.
- После получения токена сохраните только `GOOGLE_OAUTH_TOKEN_V2` в `main.env`.

## Запуск

```bash
python main.py
```

## Примеры запросов

### События календаря

- `Встреча с командой завтра в 14:00 на час`
- `Планерка каждый понедельник в 10:00`
- `Стоматолог 15 августа в 16:30, описание: профилактический осмотр`

### Задачи

- `Напомни завтра в 17:00 позвонить в банк`
- `Сделать отчёт до пятницы`

### Заметки

- `Запомни: купить молоко и хлеб`
- `Идея: сделать отдельный workflow для ретроспектив`

## Работа с голосовыми

- Бот принимает Telegram voice (`.ogg`)
- Бот принимает аудиофайлы `mp3` и `wav` (через `Audio`/`Document`)
- Аудио конвертируется в 16kHz mono
- Для коротких сообщений используется `transcribe`, для длинных — `transcribe_longform`
- При пустой транскрипции создаются debug-артефакты в `debug_audio/`

## Логирование

- Лог-файл: `calendar_assistant.log`
- Логируются пользовательские запросы, промпты/ответы LLM, вызовы Google API, ошибки

## Полезные скрипты

- `scripts/list_tasklists.py` — вывести доступные tasklist id/title
- `scripts/transcribe_mp4_chunks.py` — утилита оффлайн-транскриба MP4 по чанкам

## Структура проекта

```text
selfhosted_assistant/
├── main.py
├── telegram_bot.py
├── assistant_service.py
├── request_classifier.py
├── google_calendar_client.py
├── voice_service.py
├── models.py
├── logger.py
├── model_config.json
├── llm_inference/
│   ├── model_router.py
│   ├── local_provider.py
│   ├── openrouter_provider.py
│   └── privacy_detector.py
├── request_handlers/
│   ├── classification_handler.py
│   ├── calendar_event_handler.py
│   ├── task_handler.py
│   └── note_handler.py
├── scripts/
│   ├── list_tasklists.py
│   └── transcribe_mp4_chunks.py
└── requirements.txt
```
