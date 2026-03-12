
## Исправленный план разработки: Topic-Aware Digest RAG

### Что было неверно в предыдущей версии

1. YouTube был вынесен в "будущее", хотя он входит в исходный scope.
2. План описывал только векторный поиск и саммаризацию, но не задавал контракты idempotent ingestion, dedupe и retrieval window, без которых ответы будут дублировать шум или терять контекст.
3. Локальный MCP сервер рассматривался как основной внутренний API. Для текущего репозитория это слишком рано: сначала нужен обычный Python retrieval layer, а MCP нужен как внешний интерфейс для Copilot-агента.
4. В текущем runtime нет готового маршрута для новой capability `digest_qa`: придется менять не только `capability_registry.json`, но и классификацию, routing task types и policy/mcp wiring.
5. `get_today_content(topic)` недостаточно для вопроса "что думают авторы об X?". Нужен не только сегодняшний контент, но и исторический контекст канала, иначе ответ будет пересказом последних постов, а не позиции автора.

---

### Принятые решения

| Параметр | Значение |
|----------|----------|
| **Embedding model** | `intfloat/multilingual-e5-large` на старте, с возможностью отката на `multilingual-e5-base`, если CPU contention окажется слишком высоким |
| **Vector DB** | ChromaDB, хранение в `data/chroma/` |
| **Sources v1** | Telegram + YouTube сразу через единый ingestion abstraction |
| **Архитектура доступа** | Внутренний `RetrievalService` в Python + локальный MCP facade поверх него |
| **Саммаризация** | 3 слоя: per-source digest -> topic digest -> cross-source synthesis |
| **Q&A** | Ответ с evidence snippets, указанием источников и различий между авторами |
| **Планировщик** | Отдельные джобы: ingest, digest build, digest publish |
| **Inference** | CPU only, но ingestion должен выполняться вне основного Telegram request path |

---

### Целевые сценарии

1. Каждый час система подтягивает новые посты и транскрипты, режет их на чанки и обновляет индекс без дублей.
2. Раз в день система строит дайджесты по каналам, затем сводит их в дайджесты по темам.
3. Пользователь может спросить: "что думают авторы об X?", и получить ответ по теме с учетом:
   - свежих материалов,
   - исторического контекста конкретных каналов,
   - пересечений и расхождений между авторами,
   - ссылок на источники.

---

### Ключевые архитектурные контракты

#### 1. Единая модель документа

Каждая запись перед индексацией должна иметь стабильные поля:

```json
{
  "doc_id": "tg:ProfitGate:12345",
  "source_type": "telegram",
  "source_id": "ProfitGate",
  "external_id": "12345",
  "topic_ids": ["investing"],
  "published_at": "2026-03-12T09:15:00+03:00",
  "ingested_at": "2026-03-12T10:01:00+03:00",
  "url": "https://t.me/s/ProfitGate/12345",
  "author_label": "ProfitGate",
  "language": "ru",
  "content_kind": "post",
  "content_hash": "sha256:...",
  "chunk_id": "tg:ProfitGate:12345#chunk-0",
  "parent_doc_id": "tg:ProfitGate:12345"
}
```

Без этого нельзя надежно делать upsert, dedupe, re-ingestion и traceability в ответах.

#### 2. Idempotent ingestion

`ingestion_state.json` должен хранить не просто lookback days, а per-source state:

```json
{
  "telegram:ProfitGate": {
    "last_seen_external_id": "12345",
    "last_seen_published_at": "2026-03-12T09:15:00+03:00",
    "last_success_at": "2026-03-12T10:01:00+03:00"
  }
}
```

Дополнительно нужен dedupe по `doc_id` и `content_hash`, иначе одинаковые посты и обновленные транскрипты будут плодить дубли в индексе.

#### 3. Retrieval не только по "сегодня"

Для качественного ответа нужны как минимум три окна данных:

1. `recent_window`: последние 24-72 часа для текущей повестки.
2. `context_window`: 30-90 дней для понимания устойчивой позиции канала.
3. `topic_neighbors`: релевантные куски из других каналов той же темы.

#### 4. Дайджест не должен строиться напрямую из raw chunks

Пайплайн должен быть таким:

1. retrieval свежих документов по каждому источнику;
2. выделение claims/topics/events;
3. clustering/near-dedup между каналами;
4. per-source summary;
5. topic-level synthesis с пометкой consensus/divergence.

Иначе одинаковая новость из 5 каналов станет "5 отдельными важными событиями".

---

### Файловая структура

```
digest/
  __init__.py
  config.py                 # Загрузка digest_config.json и валидация схемы
  models.py                 # SourceConfig, TopicConfig, DigestDocument, RetrievalQuery
  source_base.py            # Общий контракт для источников
  telegram_source.py        # Инжест из Telegram
  youtube_source.py         # RSS + transcript ingestion для YouTube
  index_store.py            # ChromaDB + embedding model + upsert/search/delete
  ingestion.py              # Batch ingestion, chunking, dedupe, checkpoints
  retrieval_service.py      # get_recent_content, semantic_search, source_profile
  digest_builder.py         # Per-source digest + topic synthesis + clustering
  mcp_server.py             # MCP facade поверх retrieval_service.py
  qa_handler.py             # Q&A orchestration поверх retrieval_service.py/MCP
  scheduler.py              # APScheduler jobs и lock/overlap protection
  runner.py                 # CLI entrypoints

digest_config.json

data/
  chroma/
  ingestion_state.json
  digests/

scripts/
  run_digest.py             # python scripts/run_digest.py ingest|digest|publish|mcp

tests/
  test_digest_config.py
  test_digest_ingestion.py
  test_digest_retrieval.py
  test_digest_builder.py
  test_digest_runtime_integration.py
```

---

### Конфиг: `digest_config.json`

```json
{
  "topics": {
    "investing": {
      "label": "Инвестиции и финансы",
      "query_aliases": ["инвестиции", "рынок", "акции", "облигации"]
    },
    "business": {
      "label": "Бизнес и предпринимательство",
      "query_aliases": ["бизнес", "предпринимательство", "стратегия"]
    }
  },
  "sources": [
    {
      "source_id": "telegram:VectorCapital_Investments",
      "type": "telegram",
      "slug": "VectorCapital_Investments",
      "topic_ids": ["investing"],
      "enabled": true
    },
    {
      "source_id": "youtube:UC_xxx",
      "type": "youtube",
      "channel_id": "UC_xxx",
      "topic_ids": ["investing"],
      "enabled": true
    }
  ],
  "embedding_model": "intfloat/multilingual-e5-large",
  "chroma_path": "data/chroma",
  "state_path": "data/ingestion_state.json",
  "digest_output_path": "data/digests",
  "recent_window_hours": 36,
  "source_profile_days": 60,
  "ingestion_interval_minutes": 60,
  "digest_schedule": "0 21 * * *",
  "digest_chat_id": null
}
```

Важно: источник должен ссылаться на `topic_ids`, а не быть жестко вложенным в тему. Один и тот же канал может покрывать несколько тем.

---

### Интеграция с текущим runtime

Это обязательная часть плана, иначе новая возможность не войдет в существующий бот.

1. Добавить новый intent/task type, например `digest_qa`, либо осознанно расширить существующий `research` так, чтобы он умел работать с локальным knowledge source.
2. Обновить `capability_registry.json` для новой capability.
3. Обновить `llm_routing_config.json`, потому что сейчас новые task types туда не входят.
4. Если использовать MCP внутри Copilot session, расширить provider: сейчас runtime фактически умеет пробрасывать только `tavily`.
5. В `telegram_bot.py` и `chat_application_service.py` добавить явный путь для `/digest` и пользовательского вопроса к digest QA.

Практический вывод: сначала делаем внутренний Python API (`RetrievalService`, `DigestBuilder`, `QAHandler`), и только потом MCP facade для агентов. Так проще тестировать и проще встроить в текущий runtime.

---

### Исправленный порядок реализации

### Итерация 1: Config + Models + Index Store

**Файлы:** `digest/__init__.py`, `digest/config.py`, `digest/models.py`, `digest/index_store.py`, `digest_config.json`

**Что делаем:**
1. Валидируем конфиг, источники, topic bindings и пути.
2. Описываем документную модель и metadata schema.
3. Реализуем `IndexStore` с upsert/delete/search и фильтрацией по `topic_ids`, `source_id`, `published_at`.
4. Пишем тесты на idempotent upsert и retrieval filters.

**Результат:** индекс создается программно и умеет надежно обновляться без дублей.

---

### Итерация 2: Telegram + YouTube ingestion

**Файлы:** `digest/source_base.py`, `digest/telegram_source.py`, `digest/youtube_source.py`, `digest/ingestion.py`

**Что делаем:**
1. Вводим единый интерфейс `fetch_items(since_state) -> list[RawSourceItem]`.
2. Для Telegram реализуем сбор постов с устойчивым `external_id`.
3. Для YouTube реализуем RSS discovery + transcript retrieval.
4. Чанкуем через `SentenceSplitter(chunk_size=500, chunk_overlap=50)`.
5. Сохраняем `doc_id`, `content_hash`, state checkpoints и статистику ingestion.

**Результат:** оба источника наполняют индекс единообразно и повторный прогон не создает мусор.

---

### Итерация 3: Retrieval layer

**Файлы:** `digest/retrieval_service.py`

**Минимальный API:**
1. `get_recent_content(topic_id, hours=36, per_source_limit=20)`
2. `semantic_search(query, topic_id, k=8, days=30)`
3. `get_source_profile(topic_id, source_id, days=60)`
4. `find_related_across_sources(query, topic_id, k=12)`

**Что важно:**
1. Ответы должны возвращать не просто текст, а `snippet + source_id + published_at + url + score`.
2. Retrieval должен поддерживать сочетание vector similarity и metadata filters.

**Результат:** есть надежный слой данных, который можно использовать и из Python, и из MCP.

---

### Итерация 4: Digest builder

**Файлы:** `digest/digest_builder.py`

**Пайплайн:**
1. Собрать свежие материалы по источнику.
2. Убрать near-duplicates и сгруппировать по подтемам/событиям.
3. Построить `source digest` по каждому каналу.
4. Свести `topic digest`, отметив:
   - что совпадает между авторами;
   - где мнения расходятся;
   - какие тезисы новые сегодня, а какие продолжают долгий нарратив.

**Результат:** дайджест отражает не просто сумму постов, а картину по теме.

---

### Итерация 5: QA pipeline

**Файлы:** `digest/qa_handler.py`

**Логика ответа на "что думают авторы об X?":**
1. Определить тему или запросить уточнение.
2. Взять свежий контекст по теме.
3. Взять исторический `source profile` по релевантным каналам.
4. Собрать evidence snippets из нескольких источников.
5. Сформировать ответ в виде:
   - краткий вывод;
   - кто скорее "за" / "против" / "нейтрален";
   - на чем основан вывод;
   - что пока не подтверждено.

**Результат:** бот отвечает не только по последнему посту, а по накопленной позиции авторов.

---

### Итерация 6: MCP facade + runtime wiring

**Файлы:** `digest/mcp_server.py`, `capability_registry.json`, `llm_routing_config.json`, `telegram_bot.py`, `chat_application_service.py`, при необходимости `integrations/copilot_sdk/provider.py`

**Что делаем:**
1. Поднимаем MCP facade поверх `RetrievalService`.
2. Добавляем capability и task type для digest QA.
3. Добавляем команду `/digest` и явный бот-флоу для запуска дайджеста.
4. Решаем, идет ли Q&A через MCP в Copilot session или через прямой host-side Python путь.

**Результат:** новая возможность реально встроена в текущий бот, а не существует отдельно от него.

---

### Итерация 7: Scheduler + публикация

**Файлы:** `digest/scheduler.py`, `digest/runner.py`, `scripts/run_digest.py`

**Что делаем:**
1. Ingestion job каждый час.
2. Digest build job раз в день.
3. Publish job в Telegram.
4. Lock/overlap protection, чтобы новый ingest не стартовал поверх незавершенного.

**Результат:** пайплайн работает автономно и предсказуемо.

---

### Что добавить в тесты

1. Повторный ingestion одного и того же поста не создает дубли.
2. Измененный transcript корректно переиндексируется.
3. Retrieval по теме не подтягивает документы из нерелевантных topic groups.
4. Digest builder склеивает одинаковый инфоповод из нескольких источников.
5. QA pipeline возвращает источники и умеет отвечать "недостаточно данных".
6. Runtime integration проверяет, что новый route реально доходит до бота.

---

### Что добавить в `.gitignore`

```
data/
```

---

### Новые зависимости

```
llama-index-core>=0.11
llama-index-vector-stores-chroma>=0.2
llama-index-embeddings-huggingface>=0.3
chromadb>=0.5
sentence-transformers>=3.0
youtube-transcript-api>=0.6
feedparser>=6.0
APScheduler>=3.10
```

---

### Практические замечания по CPU

1. `multilingual-e5-large` на CPU допустим для batch ingestion, но не должен крутиться в том же горячем пути, что и ответы Telegram или voice pipeline.
2. Первую загрузку модели и warm-up лучше выполнять до старта расписания.
3. Если на той же машине активно используется ASR, стоит сразу предусмотреть fallback на более легкую embedding model.

---

### Рекомендуемый старт реализации

Начинать не с MCP, а с `config/models/index_store/ingestion/retrieval_service`. Это даст проверяемое ядро системы. После этого уже безопасно встраивать агентов, MCP и Telegram delivery.