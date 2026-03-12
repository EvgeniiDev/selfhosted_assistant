
## Финальный план разработки: Content Digest RAG

### Принятые решения

| Параметр | Значение |
|----------|----------|
| **Embedding model** | `intfloat/multilingual-e5-large` (560M, CPU, multilingual) |
| **Vector DB** | ChromaDB, хранение в `data/chroma/` |
| **Ingestion** | Web scraping `t.me/s/` + chunking (SentenceSplitter 512) |
| **Архитектура доступа** | LlamaIndex MCP Server (локальный) |
| **LLM суммаризации** | Агентный подход (Главный агент -> Субагенты по каналам) |
| **Доставка & Q&A** | Telegram Bot (существующий telegram_bot.py, новая capability `digest_qa`) |
| **Inference** | CPU only |

---

### Файловая структура (новое)

```
digest/
  __init__.py
  config.py                 # Загрузка digest_config.json
  telegram_source.py        # Обёртка над скриптом экспорта каналов
  index_store.py            # Управление коллекциями ChromaDB и индексами
  ingestion.py              # Сбор данных, chunking через SentenceSplitter(512) и upsert
  mcp_server.py             # LlamaIndex MCP сервер (поиск по базе, отдача документов)
  orchestrator_agent.py     # Главный агент дайджестов (запускает субагентов)
  qa_handler.py             # Интеграция с ботом для ответов на вопросы пользователя (Q&A)
  runner.py                 # Точки входа (CLI/CRON)

digest_config.json          # Конфиг: источники, расписание

data/                       # gitignored
  chroma/                   # Персистентные файлы ChromaDB
  ingestion_state.json      # Checkpoints по источникам

scripts/
  run_digest.py             # Shortcut: python scripts/run_digest.py ingest/mcp/digest

tests/
  test_digest_ingestion.py  # Тесты ingestion pipeline
  test_digest_mcp.py        # Тесты MCP сервера и агентов
```

---

### Конфиг: `digest_config.json`

```json
{
  "topics": {
    "investing": {
      "label": "Инвестиции и финансы",
      "sources": [
        { "type": "telegram", "slug": "VectorCapital_Investments" },
        { "type": "telegram", "slug": "ProfitGate" },
        { "type": "telegram", "slug": "Polyakov_Ant" }
      ]
    },
    "business": {
      "label": "Бизнес и предпринимательство",
      "sources": [
        { "type": "telegram", "slug": "BizLike" },
        { "type": "telegram", "slug": "profitanet" },
        { "type": "telegram", "slug": "CashflowTime" }
      ]
    }
  },
  "embedding_model": "intfloat/multilingual-e5-large",
  "chroma_path": "data/chroma",
  "state_path": "data/ingestion_state.json",
  "ingestion_days": 1,
  "digest_chat_id": null
}
```

---

### Итерация 1: Конфиг + Index Store

**Файлы:** `digest/__init__.py`, `digest/config.py`, `digest/index_store.py`, `digest_config.json`

**Основная логика:**
1. Парсинг `digest_config.json` (информация по источникам, расписанию, путям).
2. Реализация обертки над `ChromaDB` и `LlamaIndex` (`index_store.py`).
   - Инициализация `HuggingFaceEmbedding(model_name="intfloat/multilingual-e5-large", query_instruction="query: ", text_instruction="passage: ")`.
   - Методы работы с коллекциями ChromaDB: создание, upsert, поиск. 
3. Написание базовых юнит-тестов (добавление фейковыми документов и их проверка).

---

### Итерация 2: Ingestion Job с чанкованием

**Файлы:** `digest/telegram_source.py`, `digest/ingestion.py`

**Основная логика:**
1. Адаптер для получения постов и преобразования их в `LlamaIndex Document` с метаданными (channel, date, message_id).
2. Обязательный **сплиттинг контента**: использование `SentenceSplitter(chunk_size=500, chunk_overlap=50)` для нарезки длинных постов или транскриптов. Это необходимо из-за лимита в 512 токенов модели `multilingual-e5-large`. Метаданные сохраняются для каждого чанка.
3. Добавление чанков в `IndexStore` по темам и сохранение прогресса в `ingestion_state.json`.

---

### Итерация 3: MCP-сервер LlamaIndex

**Файл:** `digest/mcp_server.py`

Реализация локального сервера MCP, который является интерфейсом между базой знаний и LLM-агентами:
- **`get_today_content(topic)`**: возвращает сырые тексты или узлы из базы за текущий день для конкретной темы, сгруппированные по каналам.
- **`semantic_search_in_topic(query, topic, k=5)`**: поиск релевантных материалов по вопросу (используется для Q&A и глубокого ресёрча).
- Сервер скрывает детали работы с ChromaDB и эмбеддингами за стандартизированным API.

---

### Итерация 4: Агенты для Дайджеста и Q&A Пайплайн

**Файлы:** `digest/orchestrator_agent.py`, `digest/qa_handler.py`

**Генерация дайджеста (Orchestrator Agent):**
- Главный агент запрашивает через MCP инструменты наличие новых постов за сегодня по темам.
- Для каждой темы или отдельного канала главный агент **параллельно запускает субагента** (Map-Reduce). 
- Субагенты делают выжимки (избегая переполнения контекста), опираясь на правила.
- Главный агент собирает выжимки. При этом он ищет пересечения между каналами с помощью LLM: "если разные каналы пишут об одном и том же — объедини и отметь".

**Пользовательский Q&A Pipeline ("Что думают авторы об X?"):**
- Внедрение нового скилла в `capability_registry.json`.
- Обработчик (`qa_handler.py`) берет вопрос пользователя, определяет тематику.
- Агент вызывает инструмент MCP `semantic_search_in_topic` для сбора контекста по заданному вопросу.
- LLM формирует ответ, учитывая специфику источников и каналов.

---

### Итерация 5: Telegram-интеграция и Автоматизация (Cron)

**Обновления в боте и инфраструктуре:**
1. **Команда `/digest`** (`telegram_bot.py`) — триггерит оркестратора на генерацию сводки "здесь и сейчас".
2. **Фоновая база (Ingestion)** — добавить запуск `ingestion.py` каждый час (через Windows Task Scheduler или APScheduler).
3. **Ежедневный дайджест** — запускать генерацию и отправку дайджеста по крону в нужное время (например 21:00).

---

### Итерация 6 (будущее): YouTube source

1. Получение RSS: `https://www.youtube.com/feeds/videos.xml?channel_id=XXX`
2. Извлечение транскриптов через `youtube_transcript_api`.
3. Обязательный Chunking длинных транскриптов (`SentenceSplitter`, chunk_size=512) перед отправкой в Chroma.

---

### Порядок реализации

| # | Итерация | Что делаем | Результат |
|---|----------|-----------|-----------|
| 1 | Config + Index Store | `digest/config.py`, `index_store.py` | Можно программно создать индекс и добавлять/искать документы. |
| 2 | TG Source + Ingestion | `telegram_source.py`, `ingestion.py` | Скрипт собирает посты, чанкует их и сохраняет в векторную БД. |
| 3 | LlamaIndex MCP Server | `mcp_server.py` | Запущен локальный MCP сервер, отдающий тулзы поиска и выборки контента по дням. |
| 4 | Дайджест-Агенты и Q&A | `orchestrator_agent.py`, `qa_handler.py` | Главный агент собирает выжимку через субагентов, бот может отвечать на "Что об этом думают?". |
| 5 | Бот и Автоматизация | CLI/Cron, `/digest` | Интеграция в Telegram, запуск по крону/Task Scheduler. |
| 6 | YouTube (опционально) | `youtube_source.py` | Транскрипты в индексе и базе. |

### Что добавить в .gitignore

```
data/
```

### Новые зависимости

```
llama-index-core>=0.11
llama-index-vector-stores-chroma>=0.2
llama-index-embeddings-huggingface>=0.3
chromadb>=0.5
sentence-transformers>=3.0
```

---

По `intfloat/multilingual-e5-large` на CPU: модель 560M параметров, первая загрузка ~2.2 GB, embedding одного поста ~200-500ms на CPU. Для batch ingestion (десятки постов раз в час) — вполне нормально. При первом запуске модель скачается в `~/.cache/huggingface/`.

Готов начать реализацию с итерации 1?