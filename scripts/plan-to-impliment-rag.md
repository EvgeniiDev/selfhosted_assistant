
## Финальный план разработки: Content Digest RAG

### Принятые решения

| Параметр | Значение |
|----------|----------|
| **Embedding model** | `intfloat/multilingual-e5-large` (560M, CPU, multilingual) |
| **Vector DB** | ChromaDB, хранение в `data/chroma/` |
| **TG ingestion** | Web scraping через `t.me/s/` (как в export_channels.py), без ключей |
| **LLM суммаризации** | Copilot через существующий `LLMGateway` → `gpt-5.4` |
| **Доставка** | Telegram Bot (существующий telegram_bot.py) |
| **Inference** | CPU only |

---

### Файловая структура (новое)

```
digest/
  __init__.py
  config.py                 # Загрузка digest_config.json, dataclasses конфига
  telegram_source.py        # Обёртка над export_channels.iter_channel_posts
  index_store.py            # Chroma + LlamaIndex + e5-large embeddings
  ingestion.py              # Job: fetch → chunk → upsert в индекс
  summarizer.py             # Job: retrieve today → LLM map-reduce → markdown
  runner.py                 # CLI точка входа: run ingestion / run digest

digest_config.json          # Источники по топикам, расписание, chat_id

data/                       # gitignored
  chroma/                   # Персистентные файлы ChromaDB
  ingestion_state.json      # Checkpoint: last_indexed_at per source

scripts/
  run_digest.py             # Shortcut: python scripts/run_digest.py ingest|digest|both

tests/
  test_digest_ingestion.py  # Тесты ingestion pipeline
  test_digest_summarizer.py # Тесты суммаризации
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

**`digest/config.py`** — загрузка и валидация конфига:
```python
@dataclass
class SourceConfig:
    type: str        # "telegram" | "youtube"
    slug: str        # channel slug or channel_id

@dataclass
class TopicConfig:
    label: str
    sources: list[SourceConfig]

@dataclass
class DigestConfig:
    topics: dict[str, TopicConfig]
    embedding_model: str
    chroma_path: str
    state_path: str
    ingestion_days: int
    digest_chat_id: int | None

def load_config(path: Path | None = None) -> DigestConfig: ...
```

**`digest/index_store.py`** — обёртка над Chroma + LlamaIndex:
```python
class IndexStore:
    """Manages per-topic ChromaDB collections with LlamaIndex."""
    
    def __init__(self, config: DigestConfig):
        self._chroma_client = chromadb.PersistentClient(path=config.chroma_path)
        self._embed_model = HuggingFaceEmbedding(
            model_name=config.embedding_model,
            # e5 models require "query: " / "passage: " prefix
            query_instruction="query: ",
            text_instruction="passage: ",
        )
        self._indexes: dict[str, VectorStoreIndex] = {}

    def get_index(self, topic_key: str) -> VectorStoreIndex:
        """Get or create index for a topic (lazy init)."""
        ...

    def add_documents(self, topic_key: str, documents: list[Document]) -> int:
        """Add documents to topic index. Returns count added."""
        ...

    def get_today_nodes(self, topic_key: str, date_str: str) -> list[NodeWithScore]:
        """Retrieve all nodes for a given date from topic index."""
        ...
```

**Важный нюанс e5-large:** модель требует префиксы `"query: "` для запросов и `"passage: "` для документов при индексации. LlamaIndex `HuggingFaceEmbedding` поддерживает это через `query_instruction` / `text_instruction`.

**Зависимости для requirements.txt:**
```
llama-index-core>=0.11
llama-index-vector-stores-chroma>=0.2
llama-index-embeddings-huggingface>=0.3
chromadb>=0.5
sentence-transformers>=3.0
```

**Тест:** создать индекс, добавить 3 документа, retrieve по дате — проверить что возвращаются.

---

### Итерация 2: Telegram Source + Ingestion Job

**Файлы:** `digest/telegram_source.py`, `digest/ingestion.py`

**`digest/telegram_source.py`** — адаптер над export_channels.py:
```python
from scripts.export_channels import iter_channel_posts, clean_text
from llama_index.core.schema import Document

def fetch_channel_posts(slug: str, since: datetime) -> list[Document]:
    """Fetch posts from a public TG channel since cutoff date.
    Returns LlamaIndex Documents with metadata."""
    docs = []
    for post in iter_channel_posts(slug, cutoff=since):
        text = clean_text(post["text_raw"])
        if not text or len(text) < 20:  # skip noise
            continue
        docs.append(Document(
            text=text,
            metadata={
                "channel": slug,
                "date": post["date"].strftime("%Y-%m-%d"),
                "message_id": post["message_id"],
                "source_type": "telegram",
            },
        ))
    return docs
```

**`digest/ingestion.py`** — основной ingestion job:
```python
class IngestionJob:
    def __init__(self, config: DigestConfig, index_store: IndexStore):
        self.config = config
        self.index_store = index_store
        self.state = self._load_state()

    def run(self) -> dict[str, int]:
        """Run ingestion for all topics. Returns {topic: docs_added}."""
        results = {}
        for topic_key, topic in self.config.topics.items():
            count = 0
            for source in topic.sources:
                since = self._get_cutoff(source)
                if source.type == "telegram":
                    docs = fetch_channel_posts(source.slug, since)
                # future: elif source.type == "youtube": ...
                else:
                    continue
                added = self.index_store.add_documents(topic_key, docs)
                count += added
                self._update_checkpoint(source)
            results[topic_key] = count
        self._save_state()
        return results

    def _get_cutoff(self, source: SourceConfig) -> datetime:
        """Last indexed time for source, or N days ago if first run."""
        ...

    def _load_state(self) -> dict: ...
    def _save_state(self) -> None: ...
    def _update_checkpoint(self, source: SourceConfig) -> None: ...
```

**State file** (`data/ingestion_state.json`):
```json
{
  "telegram:VectorCapital_Investments": "2026-03-12T10:00:00+00:00",
  "telegram:ProfitGate": "2026-03-12T10:00:00+00:00"
}
```

**Тест:** mock `iter_channel_posts` → проверить что документы попадают в индекс с правильными metadata, checkpoint обновляется.

---

### Итерация 3: Summarizer (двухэтапный через LLMGateway)

**Файл:** `digest/summarizer.py`

**Этап 1 — Per-topic summary:**
```python
class DigestSummarizer:
    def __init__(self, config: DigestConfig, index_store: IndexStore, 
                 gateway: LLMGateway):
        self.config = config
        self.index_store = index_store
        self.gateway = gateway

    def generate_digest(self, date_str: str) -> str:
        """Generate full daily digest for all topics."""
        topic_summaries = {}
        for topic_key, topic in self.config.topics.items():
            nodes = self.index_store.get_today_nodes(topic_key, date_str)
            if not nodes:
                continue
            # Группируем по каналам
            by_channel = group_by_metadata(nodes, "channel")
            channel_texts = []
            for channel, channel_nodes in by_channel.items():
                posts_text = "\n---\n".join(n.text for n in channel_nodes)
                channel_texts.append(f"### {channel}\n{posts_text}")
            
            all_text = "\n\n".join(channel_texts)
            summary = self._summarize_topic(topic.label, all_text)
            topic_summaries[topic_key] = summary
        
        # Этап 2: cross-topic synthesis
        return self._synthesize(topic_summaries)
```

**Этап 1 prompt** (`_summarize_topic`):
```python
LLMRequest(
    content=all_text,
    task_type="digest",
    system_prompt=f"""Ты — аналитик контента. Тема: {topic_label}.
Перед тобой посты из нескольких каналов за сегодня.

Задачи:
1. Для каждого канала выдели 2-3 ключевых момента
2. Если разные каналы пишут об одном и том же — объедини и отметь
3. Пропусти рекламу, ссылки без контекста, повторы

Формат: Markdown, компактно, по-русски."""
)
```

**Этап 2 prompt** (`_synthesize`):
```python
LLMRequest(
    content="\n\n".join(
        f"## {cfg.label}\n{summary}" 
        for key, summary in topic_summaries.items()
        if (cfg := self.config.topics[key])
    ),
    task_type="digest",
    system_prompt="""Ты — персональный новостной аналитик.
Перед тобой сводки по разным темам за сегодня.

Задачи:
1. Сохрани структуру по темам
2. Если есть пересечения между темами — выдели в отдельный блок "Пересечения"
3. В конце — блок "Главное за день" (2-3 bullet points)

Формат: Markdown, компактно, по-русски."""
)
```

**Добавить `"digest"` в task_types** в llm_routing_config.json:
```json
"task_types": ["calendar_event", "task", "note", "research", "unknown", "classification", "digest"]
```

**Тест:** mock `index_store.get_today_nodes` + mock `gateway.generate` → проверить что prompt собирается правильно, финальный markdown содержит обе темы.

---

### Итерация 4: Runner + Telegram-интеграция

**Файл:** `digest/runner.py`

```python
"""CLI entry point for digest operations."""

def build_gateway() -> LLMGateway:
    """Wire up LLM gateway (same as telegram_bot does)."""
    ...

def cmd_ingest():
    config = load_config()
    store = IndexStore(config)
    job = IngestionJob(config, store)
    results = job.run()
    for topic, count in results.items():
        print(f"  {topic}: {count} documents indexed")

def cmd_digest():
    config = load_config()
    store = IndexStore(config)
    gateway = build_gateway()
    summarizer = DigestSummarizer(config, store, gateway)
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    digest_text = summarizer.generate_digest(today)
    
    if config.digest_chat_id:
        send_to_telegram(config.digest_chat_id, digest_text)
    else:
        print(digest_text)

def cmd_both():
    cmd_ingest()
    cmd_digest()

# CLI: python -m digest.runner ingest|digest|both
```

**`scripts/run_digest.py`** — shortcut:
```python
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from digest.runner import main
main()
```

**Telegram-команда** (добавить в telegram_bot.py):
```python
async def digest_command(self, update, context):
    """Handler for /digest — run digest now."""
    await message.reply_text("Генерирую дайджест...")
    # run ingestion + summarization
    digest_text = ...
    await self._send_long_message(message, digest_text, parse_mode="Markdown")
```

---

### Итерация 5: Автоматизация (cron / Task Scheduler)

Два варианта:

**A. Windows Task Scheduler** (проще для selfhosted):
```
# Ingestion каждый час
schtasks /create /tn "DigestIngestion" /tr "C:\...\\.venv\\Scripts\\python.exe scripts/run_digest.py ingest" /sc hourly

# Digest раз в день в 21:00
schtasks /create /tn "DigestDaily" /tr "C:\...\\.venv\\Scripts\\python.exe scripts/run_digest.py digest" /sc daily /st 21:00
```

**B. APScheduler в main.py** (если бот работает 24/7):
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()
scheduler.add_job(run_ingestion, 'interval', hours=1)
scheduler.add_job(run_digest, 'cron', hour=21)
scheduler.start()
```

---

### Итерация 6 (будущее): YouTube source

```python
# digest/youtube_source.py
from youtube_transcript_api import YouTubeTranscriptApi

def fetch_video_transcripts(channel_id: str, since: datetime) -> list[Document]:
    # 1. RSS: https://www.youtube.com/feeds/videos.xml?channel_id=XXX
    # 2. Фильтр по дате
    # 3. Транскрипт через YouTubeTranscriptApi.get_transcript(video_id, languages=['ru','en'])
    # 4. Chunk длинные транскрипты (SentenceSplitter, chunk_size=1024)
    ...
```

Добавить `"youtube"` type в `digest_config.json` и обработку в `ingestion.py`.

---

### Порядок реализации

| # | Итерация | Что делаем | Результат |
|---|----------|-----------|-----------|
| 1 | Config + Index Store | `digest/config.py`, `index_store.py`, `digest_config.json` | Можно программно создать индекс и добавить документы |
| 2 | TG Source + Ingestion | `telegram_source.py`, `ingestion.py` | `python scripts/run_digest.py ingest` собирает посты в Chroma |
| 3 | Summarizer | `summarizer.py` | `python scripts/run_digest.py digest` генерирует markdown-дайджест |
| 4 | Runner + TG бот | `runner.py`, команда `/digest` | Дайджест приходит в Telegram |
| 5 | Автоматизация | Task Scheduler или APScheduler | Всё работает по крону |
| 6 | YouTube | `youtube_source.py` + config | Видео-транскрипты в индексе |

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