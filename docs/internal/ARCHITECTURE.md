# Local Knowledge Platform — Refactor & Build Plan

## Executive Summary

Extract a shared core from readcast, then build Spock and the briefing agent as independent products on that core. All three install via `pixi global install` and share a single SQLite database with full-text search and vector embeddings.

**What exists today:**
- kokoro-edge — standalone TTS daemon, published to anaconda.org, `pixi global install` works
- readcast — web UI + Chrome extension + API, published to anaconda.org, `pixi global install` works
- readcast internals — SQLite/FTS5 database, LLM client (just built), TTS client, config/TOML system
- Gmail plugin — DOM scraper + LLM briefing pipeline (just built, lives inside readcast)
- Spock product spec — seven-type question taxonomy, FSRS integration, paralinguistic analysis design
- pixi-publish-to-anaconda skill — rattler-build + GitHub Actions publishing pipeline

**What we're building:**
- `localknowledge-core` — shared Python package (extracted from readcast)
- `readcast` v2 — thinner, imports core instead of owning infrastructure
- `spock` — voice-first mastery tutor, new package on core
- `briefing-agent` — scheduled gathering + synthesis, new package on core (Gmail plugin migrates here)

---

## Phase 0: Schema Design (do this first, on paper)

This is the most consequential work. Get the shared schema right before moving any code.

### 0.1 — Unified document table

Current readcast has an `articles` table shaped specifically for articles (title, url, content, audio_path, status, etc.). The core needs a generalized `documents` table that works for all content types.

```sql
CREATE TABLE documents (
    id                  TEXT PRIMARY KEY,   -- UUID
    title               TEXT NOT NULL,
    content             TEXT,               -- full text (nullable for metadata-only docs)
    summary             TEXT,               -- LLM-generated or user-provided
    content_type        TEXT DEFAULT 'text/plain',  -- text/html, text/markdown, message/rfc822
    language            TEXT,               -- ISO 639-1 code, nullable
    source_type         TEXT NOT NULL,      -- 'article', 'briefing', 'email', 'study_note', 'flashcard_source'
    source_uri          TEXT,               -- original URL, 'gmail://thread/xyz', etc.
    canonical_uri       TEXT,               -- normalized/deduped URI
    source_product      TEXT NOT NULL,      -- 'readcast', 'spock', 'briefing-agent'
    parent_document_id  TEXT,               -- briefing derived from items, chunk parents, etc.
    content_hash        TEXT,               -- SHA-256 for dedup and idempotent ingest
    ingest_status       TEXT DEFAULT 'raw', -- 'raw', 'processed', 'indexed', 'error'
    metadata            TEXT,               -- JSON blob for product-specific fields
    created_at          TEXT NOT NULL,      -- ISO 8601
    updated_at          TEXT NOT NULL,      -- ISO 8601
    deleted_at          TEXT,               -- soft delete (cross-product safety)
    FOREIGN KEY (parent_document_id) REFERENCES documents(id) ON DELETE SET NULL
);

CREATE INDEX idx_documents_source_type ON documents(source_type);
CREATE INDEX idx_documents_source_product ON documents(source_product);
CREATE INDEX idx_documents_created_at ON documents(created_at);
CREATE INDEX idx_documents_content_hash ON documents(content_hash);
CREATE INDEX idx_documents_parent ON documents(parent_document_id);
CREATE INDEX idx_documents_not_deleted ON documents(deleted_at) WHERE deleted_at IS NULL;
```

**Design decisions:**
- `source_product` is metadata, not access control — all products can read all documents
- `metadata` JSON blob handles product-specific fields without schema sprawl
- `content_hash` enables idempotent ingest — same content won't be stored twice
- `parent_document_id` tracks derivation chains (briefing composed from these 20 emails, chunk from this article)
- `deleted_at` soft delete is essential in a cross-product system — one product's delete shouldn't silently break another product's references
- `ingest_status` tracks the processing pipeline: raw → processed → indexed → error
- `canonical_uri` holds the normalized form after URL cleanup/dedup, separate from `source_uri` which preserves what was originally submitted

### 0.1a — Artifacts table (replaces audio columns)

Audio, transcripts, and other generated outputs are tracked separately from documents. This avoids baking a single audio column into the core schema when products will need multiple renditions, transcripts, cached chunks, waveform metadata, and per-card audio prompts.

```sql
CREATE TABLE artifacts (
    id              TEXT PRIMARY KEY,   -- UUID
    document_id     TEXT NOT NULL,
    artifact_type   TEXT NOT NULL,      -- 'audio', 'transcript', 'image', 'export', 'chunk'
    path            TEXT,               -- filesystem path to generated file
    status          TEXT DEFAULT 'queued', -- 'queued', 'processing', 'done', 'error'
    metadata        TEXT,               -- JSON: voice, duration_sec, format, error_message, etc.
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX idx_artifacts_document ON artifacts(document_id);
CREATE INDEX idx_artifacts_type ON artifacts(artifact_type);
CREATE INDEX idx_artifacts_status ON artifacts(status);
```

**Why this is better than audio_path on documents:**
- readcast may want multiple audio renditions (different voices, dialogue vs. narration)
- briefing-agent may want one full briefing audio plus derivative clips per topic
- Spock will want per-card audio prompts and recorded responses
- transcripts, waveform metadata, cached chunks all fit the same shape
- adding a new artifact type never requires a schema migration

FTS5 virtual table mirrors `documents` for full-text search on title + content + summary:

```sql
CREATE VIRTUAL TABLE documents_fts USING fts5(
    title, content, summary,
    content='documents',
    content_rowid='rowid'
);
```

### 0.2 — Tag hierarchy

```sql
CREATE TABLE tags (
    id          TEXT PRIMARY KEY,   -- UUID
    name        TEXT NOT NULL,      -- display name: 'Organic Chemistry', 'work', 'Anaconda'
    slug        TEXT NOT NULL UNIQUE, -- url-safe: 'organic-chemistry', 'work', 'anaconda'
    parent_id   TEXT,               -- nullable, for hierarchy (work > anaconda)
    description TEXT,               -- optional
    color       TEXT,               -- optional hex for UI rendering
    created_at  TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES tags(id) ON DELETE SET NULL
);

CREATE TABLE document_tags (
    document_id TEXT NOT NULL,
    tag_id      TEXT NOT NULL,
    confidence  REAL DEFAULT 1.0,   -- 1.0 = user-applied, <1.0 = auto-suggested
    source      TEXT DEFAULT 'user', -- 'user', 'auto_embed', 'auto_llm'
    created_at  TEXT NOT NULL,
    PRIMARY KEY (document_id, tag_id),
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
```

**Design decisions:**
- `parent_id` gives you the tree: classes > organic-chemistry > enzyme-kinetics
- `confidence` + `source` on document_tags lets products auto-tag via embeddings (confidence=0.85, source='auto_embed') and users can confirm or remove
- Tags are global — a tag created by readcast is visible to spock and briefing-agent
- **Deferred to Phase D:** `tag_relations` table for cross-cutting links (AI-governance relates_to politics, relates_to investments). The hierarchy via `parent_id` carries 90% of the value. Arbitrary graph relations are powerful but hard to keep coherent — better to add them after the products are live and the actual workflows are clear. The schema addition is trivial when the time comes

### 0.3 — Modular embedding system

The embedding layer is designed as a pluggable backend system from day one. The interface is ~20 lines and costs nothing. The implementations ship incrementally: dense embeddings in Phase A, ColBERT and graph embeddings in Phase D after the platform is proven with two live products.

#### Embedding backend interface (ships in Phase A)

Every backend implements the same abstract contract:

```python
# localknowledge/embeddings/base.py
class EmbeddingBackend(ABC):
    """Base class for all embedding strategies."""
    name: str                         # 'dense', 'colbert', 'graph', etc.

    @abstractmethod
    def embed_document(self, doc_id: str, content: str, metadata: dict) -> None:
        """Compute and store embedding(s) for a document."""
        ...

    @abstractmethod
    def find_similar(self, doc_id: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Find similar documents by ID. Returns (doc_id, score) pairs."""
        ...

    @abstractmethod
    def find_similar_by_text(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Find similar documents by query text."""
        ...

    @abstractmethod
    def remove(self, doc_id: str) -> None:
        """Remove embeddings for a document."""
        ...
```

#### Backend 1: Dense embeddings (ships in Phase A — the only backend initially)

Standard single-vector-per-document approach. Good baseline, fast, low storage.

```sql
-- Stored as JSON-serialized float arrays in a regular table
-- No sqlite-vec dependency required for v1
CREATE TABLE embeddings_dense (
    document_id TEXT PRIMARY KEY,
    embedding   BLOB NOT NULL,        -- packed float32 array (384 dims)
    model       TEXT NOT NULL,        -- model name for invalidation on model change
    created_at  TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);
```

Default model: `all-MiniLM-L6-v2` via sentence-transformers (384 dims, ~80MB, runs on CPU). On Apple Silicon, an MLX port can use the Neural Engine for faster batch indexing.

**sqlite-vec is optional, not required.** At personal KB scale (hundreds to low tens of thousands of documents), exact cosine search via numpy over the stored vectors is fast enough — sub-100ms for a 10K corpus. sqlite-vec becomes an acceleration layer when/if it stabilizes and gets proper conda packaging. The dense backend detects sqlite-vec availability at init time and uses it opportunistically:

```python
class DenseBackend(EmbeddingBackend):
    def __init__(self, db, config):
        self._use_vec = _check_sqlite_vec_available(db)
        if self._use_vec:
            self._ensure_vec_table(db)  # CREATE VIRTUAL TABLE IF NOT EXISTS
        ...

    def find_similar_by_text(self, query, top_k=10):
        if self._use_vec:
            return self._vec_search(query, top_k)   # ANN via sqlite-vec
        return self._exact_search(query, top_k)      # brute-force cosine via numpy
```

This is the "always on" backend — cheap enough to run on every document at ingest time, good enough for most discovery tasks. All products can rely on it being present.

#### Combining backends: hybrid search (ships in Phase A, initially wraps just FTS5 + dense)

```python
# localknowledge/embeddings/hybrid.py
class HybridSearch:
    """Combines FTS5 keyword results with embedding backend results via RRF."""

    def __init__(self, db, backends: list[EmbeddingBackend]):
        self.db = db
        self.backends = {b.name: b for b in backends}

    def search(self, query: str, top_k: int = 10,
               tag_ids: list[str] = None,
               backends: list[str] = None) -> list[SearchResult]:
        """
        FTS5 for keyword matching + active embedding backends for semantic similarity.
        Fused via reciprocal rank fusion (RRF).

        In Phase A, this is FTS5 + dense — already more capable than readcast v1.
        In Phase D, products can request specific backends or combine all active ones.
        """
        ...
```

#### Backend 2: ColBERT-style late interaction embeddings (ships in Phase D)

Instead of one vector per document, ColBERT produces one vector per *token*. Similarity is computed via MaxSim — for each query token, find the most similar document token, then sum. This captures fine-grained semantic matches that dense embeddings average away.

```sql
CREATE TABLE embeddings_colbert_tokens (
    id          INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL,
    token_idx   INTEGER NOT NULL,
    embedding   BLOB NOT NULL,        -- packed float array (128 dims typical for ColBERT)
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX idx_colbert_doc ON embeddings_colbert_tokens(document_id);
```

**Why this matters for the knowledge base:** When Spock asks "find documents related to enzyme inhibition mechanisms," dense embeddings might return anything about enzymes. ColBERT can distinguish between documents about enzyme *inhibition* specifically vs. enzyme *catalysis* — the per-token matching catches that "inhibition" token alignment.

**Implementation path:** ColBERTv2 has an MLX port (`mlx-colbert`) that runs well on Apple Silicon. The model is ~110MB (colbert-ir/colbertv2.0). At personal KB scale, we can store all token embeddings in sqlite and do brute-force MaxSim — no need for PLAID or other approximate indexing. For a 10K document corpus with ~200 tokens avg, that's ~2M token vectors × 128 dims × 4 bytes = ~1GB, which fits comfortably in memory for search.

**Retrieval strategy:** Two-stage — first narrow candidates via dense backend (fast), then re-rank via full MaxSim on token-level embeddings (accurate, brute-force over candidate set).

#### Backend 3: Graph embeddings over the tag ontology (ships in Phase D)

The tag hierarchy is a graph — tags have parent/child relationships, and documents connect to multiple tags. Graph embeddings (Node2Vec, spectral methods) can capture structural proximity that text similarity misses entirely.

```sql
CREATE TABLE embeddings_graph (
    entity_id   TEXT PRIMARY KEY,     -- document_id or tag_id
    entity_type TEXT NOT NULL,        -- 'document' or 'tag'
    embedding   BLOB NOT NULL,        -- packed float32 array (64 dims)
    created_at  TEXT NOT NULL
);
```

**Why this matters:** Two documents might be textually dissimilar but structurally close — a readcast article about supply chain risk and a briefing about semiconductor export controls might not share many words, but if they're both tagged under "geopolitics > US-China" and "investments > tech," the graph knows they're related.

**Implementation path:** For a personal KB, the tag graph is small enough (hundreds to low thousands of nodes) that simple approaches work: Node2Vec (random walks on the bipartite document-tag graph, pure Python/NumPy) or spectral embeddings from the graph Laplacian (exact solution, no training). Recompute on threshold of changes (e.g., 50 new documents since last computation) rather than on every ingest.

#### Storage and scale considerations

At personal knowledge base scale, sqlite handles everything comfortably:
- **Dense (384d):** 10K docs × 384 × 4 bytes = ~15MB. Trivial.
- **ColBERT (128d × ~200 tokens/doc):** 10K docs = ~1GB. Fits in RAM for search, sqlite for persistence.
- **Graph (64d):** 10K docs + 1K tags = ~2.5MB. Trivial.
- **Total:** Well under 2GB even at 10K documents with all three backends active.

#### Configuration

```toml
[embeddings]
# Phase A: just dense. Phase D: add "colbert", "graph"
backends = ["dense"]

[embeddings.dense]
model = "all-MiniLM-L6-v2"
device = "cpu"                    # "cpu", "mps", "cuda"
use_sqlite_vec = "auto"           # "auto" (detect), "yes" (require), "no" (force exact search)
```

**Design decisions:**
- Dense backend is always active — it's the baseline that every product can rely on
- The abstract interface ships in Phase A even though only dense is implemented. It's 20 lines. Designing for pluggability now prevents a painful refactor when ColBERT/graph are added in Phase D
- sqlite-vec is opportunistic, not required, for the initial release
- ColBERT and graph backends ship in Phase D after the platform is proven with two live products
- The backend interface is extensible for future strategies (HyDE, SPLADE, Mountain Discovery) without changing product code
- All computation runs locally — no embedding API calls to external services

### 0.4 — Product-specific tables (owned by each product, not by core)

Core provides a migration system so products can register their own tables in the shared database.

**Spock-owned tables:**
```sql
CREATE TABLE spock_cards (
    id          TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,       -- source document
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    card_type   TEXT NOT NULL,       -- from the 7-type taxonomy
    metadata    TEXT,                -- JSON: hints, difficulty params, etc.
    created_at  TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE spock_reviews (
    id          TEXT PRIMARY KEY,
    card_id     TEXT NOT NULL,
    -- FSRS state fields
    stability   REAL NOT NULL,
    difficulty  REAL NOT NULL,
    due_at      TEXT NOT NULL,
    last_review TEXT,
    rating      INTEGER,            -- 1=again, 2=hard, 3=good, 4=easy
    -- Paralinguistic analysis results
    confidence_score REAL,          -- from voice analysis
    hesitation_ms    INTEGER,
    metadata    TEXT,                -- JSON for extended analysis
    created_at  TEXT NOT NULL,
    FOREIGN KEY (card_id) REFERENCES spock_cards(id) ON DELETE CASCADE
);
```

**Briefing-agent-owned tables:**
```sql
CREATE TABLE briefing_sources (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,       -- 'Gmail inbox', 'HN front page'
    source_type TEXT NOT NULL,       -- 'gmail_api', 'dom_scrape', 'rss', 'api'
    config      TEXT NOT NULL,       -- JSON: auth, filters, limits
    tag_id      TEXT,                -- auto-tag gathered docs with this tag
    schedule    TEXT,                -- cron expression: '0 6 * * *' = daily at 6am
    enabled     INTEGER DEFAULT 1,
    last_run    TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE SET NULL
);

CREATE TABLE briefing_runs (
    id          TEXT PRIMARY KEY,
    source_ids  TEXT NOT NULL,       -- JSON array of source IDs included
    document_id TEXT,                -- the generated briefing document
    item_count  INTEGER,
    status      TEXT NOT NULL,       -- 'gathering', 'synthesizing', 'generating_audio', 'done', 'error'
    error       TEXT,
    started_at  TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL
);
```

---

## Phase 1: Extract Core from Readcast

**Goal:** Create `localknowledge-core` as a standalone Python package. Readcast continues to work but now imports from core.

### 1.1 — Create the core package repository

```
localknowledge/                        # monorepo
├── packages/
│   └── core/
│       ├── pyproject.toml
│       ├── recipe/recipe.yaml
│       ├── src/
│       │   └── localknowledge/
│       │       ├── __init__.py
│       │       ├── db.py              # Connection management, WAL, migrations
│       │       ├── documents.py       # CRUD for documents table, FTS5 search
│       │       ├── artifacts.py       # CRUD for artifacts (audio, transcripts, exports)
│       │       ├── tags.py            # CRUD for tags, document_tags, hierarchy
│       │       ├── embeddings/
│       │       │   ├── __init__.py    # Exports HybridSearch, EmbeddingBackend
│       │       │   ├── base.py        # Abstract EmbeddingBackend interface
│       │       │   ├── dense.py       # Phase A: single-vector, numpy exact + optional sqlite-vec
│       │       │   ├── colbert.py     # Phase D: token-level late interaction
│       │       │   ├── graph.py       # Phase D: graph embeddings over tag ontology
│       │       │   ├── hybrid.py      # RRF fusion across FTS5 + active backends
│       │       │   └── registry.py    # Backend discovery + initialization from config
│       │       ├── llm.py             # Thin OpenAI-compatible client (from readcast)
│       │       ├── tts.py             # Thin kokoro-edge HTTP client (from readcast)
│       │       ├── config.py          # TOML config, ~/.localknowledge/
│       │       └── migrations/
│       │           ├── __init__.py
│       │           └── v001_initial.py
│       └── tests/
│           ├── test_db.py
│           ├── test_documents.py
│           ├── test_artifacts.py
│           ├── test_tags.py
│           ├── test_embeddings_dense.py
│           ├── test_embeddings_hybrid.py
│           ├── test_llm.py
│           └── test_tts.py
```

### 1.2 — Migration system

Core needs a simple migration runner since multiple products will add tables over time.

```python
# localknowledge/db.py
class Database:
    def __init__(self, db_path="~/.localknowledge/store.db"):
        ...

    def migrate(self, migrations: list[Migration]):
        """Run pending migrations. Called by each product on startup."""
        ...

    def register_product_migrations(self, product_name: str, migrations: list[Migration]):
        """Products register their own migrations (e.g., spock_cards table)."""
        ...
```

Migration table tracks what's been applied:
```sql
CREATE TABLE _migrations (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    product     TEXT NOT NULL,        -- 'core', 'readcast', 'spock', 'briefing-agent'
    applied_at  TEXT NOT NULL
);
```

### 1.2a — SQLite concurrency discipline

A shared database across three products requires explicit concurrency rules. SQLite handles this well if you're disciplined.

**Required database configuration (set on every connection):**
```python
# localknowledge/db.py — applied in Database.__init__
conn.execute("PRAGMA journal_mode=WAL")      # concurrent readers + one writer
conn.execute("PRAGMA busy_timeout=5000")      # 5s wait instead of immediate SQLITE_BUSY
conn.execute("PRAGMA foreign_keys=ON")        # enforce FK constraints
conn.execute("PRAGMA synchronous=NORMAL")     # safe with WAL, better write perf
```

**Rules for products:**
- Migrations run transactionally and hold exclusive locks briefly — products should migrate on startup, not at runtime
- Ingest operations must be idempotent — use `content_hash` + `INSERT OR IGNORE` or `ON CONFLICT` to avoid duplicates
- Background jobs (embedding computation, audio generation) should batch writes and hold write locks for minimal duration
- No product should hold a transaction open while doing network I/O (LLM calls, TTS synthesis, web scraping)
- Long-running reads (search, listing) use WAL snapshot isolation and don't block writers

### 1.3 — Core API surface

The key classes/functions that products import:

```python
from localknowledge import Database, Config
from localknowledge.documents import DocumentStore
from localknowledge.tags import TagStore
from localknowledge.embeddings import EmbeddingRegistry, HybridSearch
from localknowledge.llm import LLMClient
from localknowledge.tts import TTSClient

# Typical product startup:
config = Config.load()  # reads ~/.localknowledge/config.toml
db = Database(config.db_path)
db.migrate(CORE_MIGRATIONS)
db.register_product_migrations("spock", SPOCK_MIGRATIONS)

docs = DocumentStore(db)
tags = TagStore(db)

# Embedding backends initialize from config — only active backends are loaded
embedding_registry = EmbeddingRegistry(db, config.embeddings)
search = HybridSearch(embedding_registry.active_backends())

# Products can also access specific backends directly
dense = embedding_registry.get("dense")        # always available
colbert = embedding_registry.get("colbert")    # None if not configured

llm = LLMClient(config.llm)
tts = TTSClient(config.tts)
```

### 1.4 — Config unification

Current readcast config lives at `~/.readcast/config.toml`. Core config moves to `~/.localknowledge/config.toml`.

```toml
[database]
path = "~/.localknowledge/store.db"

[tts]
server_url = "http://127.0.0.1:7777"
default_voice = "af_heart"

[llm]
provider = "local"              # "local", "openai", "anthropic"
local_model = "mlx-community/Qwen3.5-4B-MLX-4bit"
local_server_url = "http://127.0.0.1:8090"
api_key = ""
auto_start = true
startup_timeout_sec = 120

[embeddings]
# See Phase 0.3 for full modular embedding configuration
# backends, model choices, device settings, recompute schedules
backends = ["dense"]              # start minimal, add "colbert", "graph" when ready

# Product-specific sections
[readcast]
server_port = 8765
default_tags = ["reading-list"]

[spock]
default_voice = "am_fenrir"     # different voice for tutor
session_duration_min = 15

[briefing]
schedule = "0 6 * * *"          # default: daily at 6am
delivery = "audio"              # "audio", "text", "both"
```

### 1.5 — Readcast v2 refactor

Readcast's internal modules get replaced with core imports:

| Current readcast module | Becomes |
|---|---|
| `readcast.core.database` | `localknowledge.db` + `localknowledge.documents` |
| `readcast.core.llm` | `localknowledge.llm` |
| `readcast.core.config` (LLM parts) | `localknowledge.config` |
| TTS calling code | `localknowledge.tts` |
| `articles` table | `documents` table (with `source_product='readcast'`) |
| `articles.audio_path` / `audio_status` | `artifacts` table (type='audio') |

Readcast keeps:
- Its web UI (FastAPI + React frontend)
- The Chrome extension
- Article extraction / smart scraping logic
- The podcast generation pipeline (multi-voice, dialogue format)
- Its own API routes (`/api/articles`, `/api/voices`, etc.)

The readcast API would map its existing article-centric endpoints onto the core document + artifact stores:
```python
# readcast/api/app.py
from localknowledge.documents import DocumentStore, ArtifactStore

@app.get("/api/articles")
async def list_articles():
    articles = docs.list(source_product="readcast")
    # Attach audio artifact status for backward compatibility
    for a in articles:
        a["audio"] = artifacts.get_latest(a["id"], artifact_type="audio")
    return articles

@app.post("/api/articles")
async def add_article(url: str, tags: list[str] = []):
    doc = docs.create(
        title=extracted.title,
        content=extracted.content,
        content_type="text/html",
        source_type="article",
        source_uri=url,
        source_product="readcast",
        content_hash=hashlib.sha256(extracted.content.encode()).hexdigest(),
    )
    for tag_name in tags:
        tag = tag_store.get_or_create(tag_name)
        tag_store.tag_document(doc.id, tag.id)
    dense.embed_document(doc.id, doc.content, {})
    return doc
```

### 1.6 — Data migration

Existing readcast users need their data migrated to the new schema.

```python
# readcast v2 startup check
def migrate_from_v1():
    """One-time migration from ~/.readcast/readcast.db to ~/.localknowledge/store.db"""
    old_db = Path("~/.readcast/readcast.db").expanduser()
    if not old_db.exists():
        return

    # Copy articles → documents + artifacts
    for article in old_articles:
        doc = docs.create(
            title=article.title,
            content=article.content,
            content_type="text/html",
            source_type="article",
            source_uri=article.url,
            source_product="readcast",
            content_hash=hashlib.sha256(article.content.encode()).hexdigest(),
            ingest_status="indexed",
            metadata=json.dumps({"v1_id": article.id}),
        )
        # Migrate audio as an artifact
        if article.audio_path:
            artifacts.create(
                document_id=doc.id,
                artifact_type="audio",
                path=article.audio_path,
                status=article.status or "done",
            )

    # Mark migration complete
    old_db.rename(old_db.with_suffix(".db.v1.bak"))
```

---

## Phase 2: Build the Briefing Agent

**Goal:** Standalone product that gathers information on a schedule and produces audio briefings.

### 2.1 — Package structure

```
briefing-agent/
├── pyproject.toml
├── pixi.toml
├── recipe/
│   └── recipe.yaml
├── src/
│   └── briefing/
│       ├── __init__.py
│       ├── cli.py             # CLI: briefing run, briefing schedule, briefing sources
│       ├── scheduler.py       # Cron-based scheduler (APScheduler or simple loop)
│       ├── gatherers/
│       │   ├── __init__.py
│       │   ├── base.py        # Abstract Gatherer interface
│       │   ├── gmail.py       # Gmail API gatherer (upgraded from DOM scraper)
│       │   ├── rss.py         # RSS/Atom feed gatherer
│       │   ├── web_scrape.py  # Generic page scraper
│       │   └── calendar.py    # Google Calendar API gatherer
│       ├── synthesizer.py     # LLM-based cross-source synthesis
│       ├── delivery.py        # Output: audio file, RSS feed, iMessage, webhook
│       └── migrations/
│           └── v001_briefing_tables.py
└── tests/
```

### 2.2 — Gatherer interface

```python
# briefing/gatherers/base.py
from dataclasses import dataclass
from abc import ABC, abstractmethod

@dataclass
class GatheredItem:
    title: str
    content: str
    source_uri: str
    timestamp: str
    metadata: dict  # gatherer-specific fields

class Gatherer(ABC):
    @abstractmethod
    async def gather(self, config: dict, since: str | None = None) -> list[GatheredItem]:
        """Fetch items from the source, optionally since a timestamp."""
        ...

    @abstractmethod
    def validate_config(self, config: dict) -> bool:
        """Check that auth/settings are valid."""
        ...
```

### 2.3 — Gmail upgrade path

The current DOM scraper (gmail.js in the Chrome extension) moves here as a starting point, but the target is Gmail API:

1. **Phase 2a** — Keep DOM scraper as-is, move the server-side plugin runner from readcast to briefing-agent
2. **Phase 2b** — Add Gmail API gatherer using OAuth (headless, no browser needed)
3. **Phase 2c** — Deprecate DOM scraper once API path is stable

Gmail API setup:
- Google Cloud project with Gmail API enabled
- OAuth 2.0 credentials (installed app flow, token stored in `~/.localknowledge/tokens/`)
- Scopes: `gmail.readonly` (never send, never modify)
- Pull: list messages, get message bodies, parse MIME

### 2.4 — Synthesis pipeline

```python
# briefing/synthesizer.py
async def synthesize_briefing(items: list[GatheredItem], context: SynthesisContext) -> Document:
    """
    Takes gathered items from multiple sources and produces a single
    coherent briefing document.

    The LLM prompt includes:
    - The gathered items (emails, calendar events, news, etc.)
    - The user's tag context (what topics they care about)
    - Recent documents from the knowledge base (for continuity)
    """
    # 1. Retrieve related existing documents via hybrid search
    related = search.find_similar_by_text(
        " ".join(item.title for item in items),
        top_k=5
    )

    # 2. Build synthesis prompt
    prompt = build_synthesis_prompt(items, related, context)

    # 3. Generate briefing text
    briefing_text = await llm.complete(prompt)

    # 4. Store as document
    doc = docs.create(
        title=f"Briefing — {context.date}",
        content=briefing_text,
        source_type="briefing",
        source_product="briefing-agent",
        content_hash=hashlib.sha256(briefing_text.encode()).hexdigest(),
    )

    # 5. Generate audio via kokoro-edge, store as artifact
    audio_path = await tts.synthesize(briefing_text, voice=config.briefing_voice)
    artifacts.create(
        document_id=doc.id,
        artifact_type="audio",
        path=audio_path,
        status="done",
        metadata=json.dumps({"voice": config.briefing_voice}),
    )

    return doc
```

### 2.5 — Delivery options

```python
# briefing/delivery.py

class AudioFileDelivery:
    """Drop audio file in a known directory. Simplest option."""

class RSSFeedDelivery:
    """Publish as podcast RSS feed — subscribe in any podcast app or Audiobookshelf."""

class IMessageDelivery:
    """Send audio via iMessage using macOS Shortcuts/AppleScript automation."""

class WebhookDelivery:
    """POST to a webhook URL — integrates with anything."""
```

### 2.6 — CLI

```bash
# Manual run
briefing run                          # gather all enabled sources, synthesize, deliver
briefing run --source gmail           # gather from gmail only
briefing run --tag work               # gather sources tagged 'work' only

# Source management
briefing sources list
briefing sources add gmail --config '{"max_emails": 20}'
briefing sources add rss --url https://news.ycombinator.com/rss --tag tech

# Schedule management
briefing schedule start               # start the scheduler daemon
briefing schedule stop
briefing schedule status

# Delivery config
briefing delivery set rss --output ~/.localknowledge/briefing-feed.xml
briefing delivery set imessage --phone "+1234567890"
```

---

## Phase 3: Build Spock

**Goal:** Voice-first mastery tutor using FSRS, paralinguistic analysis, and LLM-based grading.

### 3.1 — Package structure

```
spock/
├── pyproject.toml
├── pixi.toml
├── recipe/
│   └── recipe.yaml
├── src/
│   └── spock/
│       ├── __init__.py
│       ├── cli.py             # CLI: spock study, spock cards, spock stats
│       ├── tutor.py           # Main study session loop
│       ├── cards.py           # Card CRUD, generation from documents
│       ├── fsrs.py            # FSRS algorithm implementation
│       ├── grading/
│       │   ├── __init__.py
│       │   ├── llm_grader.py  # Hybrid grading: local Qwen + Claude API
│       │   └── rubrics.py     # 7-type question taxonomy rubrics
│       ├── voice/
│       │   ├── __init__.py
│       │   ├── listener.py    # Speech-to-text (Whisper via mlx-whisper)
│       │   ├── speaker.py     # TTS question delivery via kokoro-edge
│       │   └── paralinguistic.py  # Hesitation, confidence analysis
│       ├── discovery.py       # Find unstudied material via embeddings + tags
│       ├── web/               # Optional web UI (study dashboard, stats)
│       │   ├── app.py
│       │   └── static/
│       └── migrations/
│           └── v001_spock_tables.py
└── tests/
```

### 3.2 — Study session flow

```
1. User starts: `spock study --tag organic-chemistry`
2. Spock queries FSRS for due cards in that tag context
3. If no due cards, offer to generate from unprocessed documents in that tag
4. For each due card:
   a. TTS reads the question aloud (kokoro-edge)
   b. User responds verbally
   c. Whisper transcribes the response
   d. Paralinguistic analysis scores confidence/hesitation
   e. LLM grader evaluates correctness against the rubric
   f. Combined signal → FSRS rating → schedule next review
   g. TTS gives feedback ("Correct — you nailed the mechanism" or "Close — the key distinction is...")
5. Session summary: cards reviewed, accuracy, weak areas, suggested next session
```

### 3.3 — Document → Card generation

```python
# spock/cards.py
async def generate_cards(document_id: str, card_types: list[str] = None) -> list[Card]:
    """
    Generate flashcards from a document using the 7-type taxonomy:
    1. Factual recall
    2. Conceptual understanding
    3. Procedural knowledge
    4. Compare/contrast
    5. Application/transfer
    6. Analysis/evaluation
    7. Synthesis/creation

    Uses LLM to decompose the document into study-worthy questions.
    """
    doc = docs.get(document_id)
    prompt = build_card_generation_prompt(doc, card_types)
    cards_json = await llm.complete(prompt, json_mode=True)
    ...
```

### 3.4 — Discovery: finding study material across the platform

```python
# spock/discovery.py
def find_unstudied_material(tag_id: str, limit: int = 10) -> list[Document]:
    """
    Find documents in a tag context that haven't been processed into cards yet.
    Searches across ALL products — readcast articles, briefing extracts, etc.
    """
    all_docs_in_tag = docs.list(tag_id=tag_id)
    docs_with_cards = {card.document_id for card in cards.list(tag_id=tag_id)}
    return [d for d in all_docs_in_tag if d.id not in docs_with_cards][:limit]

def suggest_related_material(card_id: str, top_k: int = 5) -> list[Document]:
    """
    When a user struggles with a card, find related documents that might help.
    Uses ColBERT for precision (if available) — token-level matching catches
    specific concept overlap that dense embeddings might average away.
    """
    card = cards.get(card_id)
    return search.find_similar(
        card.document_id, top_k=top_k,
        backends=["colbert", "dense"]  # prefer ColBERT precision, dense as fallback
    )
```

---

## Phase 4: Cross-Product Integration

### 4.1 — Auto-tagging pipeline (in core)

When any product stores a document, core can auto-suggest tags based on embedding similarity to existing tagged documents. The hybrid search layer means auto-tagging benefits from whichever backends are active — dense embeddings for baseline, ColBERT for precision on technical content, graph embeddings for structural placement.

```python
# localknowledge/tags.py
def auto_suggest_tags(document_id: str, threshold: float = 0.75,
                      search: HybridSearch = None) -> list[tuple[Tag, float]]:
    """
    Find tags that similar documents have, weighted by similarity score.
    Returns (tag, confidence) pairs above threshold.

    Uses hybrid search if available (combines dense + colbert + graph signals),
    falls back to dense-only if that's all that's configured.
    """
    similar_docs = search.find_similar(document_id, top_k=20)
    tag_scores = Counter()
    for doc_id, similarity in similar_docs:
        for tag in tag_store.get_tags(doc_id):
            tag_scores[tag.id] = max(tag_scores[tag.id], similarity)
    return [(tag_store.get(tid), score)
            for tid, score in tag_scores.items()
            if score >= threshold]
```

### 4.2 — Cross-product integration (direct calls, no framework)

No generic hooks framework in v1. Products that want to react to each other's data do so by querying the shared database directly. Every product already knows how to read `documents` and `document_tags` — that's the integration layer.

Example: Spock's discovery module already queries documents by tag regardless of `source_product`. The briefing agent's synthesis already searches for related existing documents via embeddings. No callback registry needed — just shared data.

**Add hooks only when:** the same "check for new documents in tag X" logic is duplicated across three or more products and the duplication is actively causing bugs. Until then, direct queries are simpler to debug and don't create hidden behavior paths.

### 4.3 — Unified search (in core)

```python
# localknowledge/search.py
def search(query: str, tag_ids: list[str] = None,
           source_products: list[str] = None,
           mode: str = "hybrid",
           backends: list[str] = None) -> list[SearchResult]:
    """
    Multi-signal search combining FTS5 keyword matching with embedding backends.

    mode: "keyword" (FTS5 only), "semantic" (embeddings only), "hybrid" (both)
    backends: which embedding backends to use (default: all active).
              Products can tune this — e.g., Spock weights ColBERT for precision,
              briefing-agent weights graph for structural relevance.
    """
    ...
```

---

## Phase 5: Publishing & Distribution

### 5.1 — Repository structure (monorepo to start)

Start as a monorepo during extraction and first product builds. Split into separate repos only after core API stabilizes and at least two products are shipping. During the extraction phase you'll be doing coordinated changes across shared schema, shared package, readcast refactor, briefing-agent, packaging recipes, and CI — that's exactly when monorepo friction is lowest and cross-repo version skew is highest.

```
localknowledge/                    # monorepo root
├── packages/
│   ├── core/                     # localknowledge-core
│   │   ├── pyproject.toml
│   │   ├── recipe/recipe.yaml
│   │   └── src/localknowledge/
│   ├── readcast/                 # readcast v2
│   │   ├── pyproject.toml
│   │   ├── recipe/recipe.yaml
│   │   └── src/readcast/
│   ├── briefing-agent/           # briefing-agent
│   │   ├── pyproject.toml
│   │   ├── recipe/recipe.yaml
│   │   └── src/briefing/
│   └── spock/                    # spock (Phase D)
│       ├── pyproject.toml
│       ├── recipe/recipe.yaml
│       └── src/spock/
├── pixi.toml                     # workspace-level pixi config
└── .github/workflows/
    ├── publish-core.yml
    ├── publish-readcast.yml
    ├── publish-briefing.yml
    └── publish-spock.yml
```

### 5.2 — Package dependency chain

```
kokoro-edge          (standalone, no core dependency)
    ↑
localknowledge-core  (standalone)
    ↑           ↑           ↑
readcast       spock    briefing-agent
```

### 5.3 — Channel strategy

Pixi uses strict channel priority. The first channel that has a package wins. Mixing defaults and conda-forge carelessly leads to ABI incompatibilities.

**Rule:** Prefer defaults for the base Python/runtime stack where compatible. Pin known compiled troublemakers to conda-forge explicitly. Don't rely on casual mixed resolution.

**Core recipe (noarch: python):**
```yaml
requirements:
  host:
    - python
    - pip
    - hatchling
  run:
    - python >=3.10
    - numpy                       # defaults has this
    - sentence-transformers       # conda-forge — pin explicitly
```

**Readcast recipe:**
```yaml
requirements:
  run:
    - python >=3.10
    - localknowledge-core >=0.1,<1.0
    - fastapi
    - uvicorn
    - httpx
    # ... existing readcast deps
```

**Install commands always specify channel order:**
```bash
pixi global install \
  --channel https://conda.anaconda.org/gjennings \
  --channel defaults \
  --channel conda-forge \
  readcast
```

Your channel first (gets your packages), then defaults (gets base Python stack), then conda-forge as fallback (gets ML libraries and anything defaults doesn't carry).

### 5.4 — Versioning strategy

- Core follows semver strictly: products pin `>=0.x,<1.0` during development, `>=1.0,<2.0` after stable
- Products version independently
- Core releases only when the shared API changes
- Products release on their own cadence
- Breaking core changes require a major version bump and product updates
- Within the monorepo, each package tags independently: `core-v0.1.0`, `readcast-v2.0.0`, etc.

---

## Implementation Sequence

Organized as phases with explicit validation gates. No phase begins until the previous gate passes. Each phase ships something usable.

### Phase A: Core Extraction + Readcast v2 (weeks 1-3)

**Goal:** Extract `localknowledge-core` from readcast. Readcast v2 ships with zero feature loss on the new substrate.

**A.1 — Schema and core package (week 1)**
- [ ] Finalize documents + artifacts + tags schema (Phase 0 design review)
- [ ] Create monorepo structure with `packages/core/` and `packages/readcast/`
- [ ] Implement `db.py` — connection management, WAL mode, busy_timeout, migration runner
- [ ] Implement `documents.py` — CRUD with soft delete, content_hash dedup, FTS5
- [ ] Implement `artifacts.py` — CRUD for audio/transcript/export artifacts
- [ ] Implement `tags.py` — CRUD, hierarchy via parent_id, document_tags with confidence
- [ ] Implement `config.py` — TOML at `~/.localknowledge/config.toml`, product sections
- [ ] Move `llm.py` from readcast (thin OpenAI-compatible client, already written)
- [ ] Move TTS client to `tts.py` (thin kokoro-edge HTTP client, already written)
- [ ] Write tests for all core modules

**A.2 — Dense embeddings (week 1-2)**
- [ ] Implement `EmbeddingBackend` abstract interface (4 methods, ~20 lines)
- [ ] Implement `DenseBackend` — sentence-transformers, BLOB storage, numpy exact search
- [ ] Implement optional sqlite-vec detection and opportunistic acceleration
- [ ] Implement `HybridSearch` — FTS5 + dense via RRF fusion
- [ ] Implement `EmbeddingRegistry` — loads backends from config
- [ ] Test: embed 100 documents, verify semantic search returns sensible results

**A.3 — Readcast v2 migration (weeks 2-3)**
- [ ] Readcast imports from `localknowledge` instead of owning infrastructure
- [ ] `articles` table → `documents` + `artifacts` tables
- [ ] Implement v1→v2 data migration (articles → documents, audio_path → artifacts)
- [ ] Update Chrome extension if any API routes changed
- [ ] All 72+ existing readcast tests pass
- [ ] Manual smoke test: add article, generate audio, play — identical to v1

**A.4 — Publish (week 3)**
- [ ] Publish `localknowledge-core` 0.1.0 to anaconda.org via rattler-build
- [ ] Publish `readcast` 2.0.0 to anaconda.org
- [ ] Verify: `pixi global install readcast` works end-to-end on a clean machine
- [ ] Verify: existing readcast users' data migrates cleanly on upgrade

**Gate A — readcast v2 validation:**
- [ ] `pixi global install readcast` pulls core as dependency, works on clean machine
- [ ] Existing readcast data migrates without loss
- [ ] All readcast features work identically to v1
- [ ] Core database is accessible and inspectable with sqlite3 CLI
- [ ] FTS5 search works across documents
- [ ] Dense embedding search returns relevant results
- [ ] Two concurrent processes (readcast web + a test script) don't corrupt the DB

---

### Phase B: Briefing Agent MVP (weeks 4-6)

**Goal:** Ship a second product on the shared substrate. Prove the core works for two real products.

**B.1 — Gatherer framework + Gmail bridge (week 4)**
- [ ] Create `packages/briefing-agent/` in monorepo
- [ ] Implement `Gatherer` abstract interface
- [ ] Migrate Gmail DOM scraper from readcast plugin → `GmailDOMGatherer`
- [ ] Implement `RSSGatherer` — fetch + parse RSS/Atom feeds
- [ ] Implement `briefing_sources` and `briefing_runs` product tables via core migrations
- [ ] Implement CLI: `briefing run`, `briefing sources list/add`

**B.2 — Synthesis + delivery (week 5)**
- [ ] Implement LLM synthesis pipeline — gathered items + existing KB context → briefing text
- [ ] Implement audio generation via core TTS client → stored as artifact
- [ ] Implement audio file delivery (drop in known directory)
- [ ] Implement RSS feed delivery (podcast feed XML)
- [ ] Auto-tag gathered documents based on source config

**B.3 — Scheduling (week 5-6)**
- [ ] Implement `briefing schedule` CLI using launchd plist generation (macOS)
- [ ] Fallback: simple cron-compatible script for manual scheduling
- [ ] Test: scheduled briefing runs unattended, audio appears in output directory

**B.4 — Publish (week 6)**
- [ ] Publish `briefing-agent` 0.1.0 to anaconda.org
- [ ] Verify: `pixi global install briefing-agent` works, connects to existing core DB

**Gate B — two-product validation:**
- [ ] briefing-agent and readcast share the same database without conflicts
- [ ] Documents created by briefing-agent are visible in readcast's search
- [ ] `briefing run` gathers Gmail inbox + RSS → produces listenable audio briefing
- [ ] Scheduled runs work via launchd without manual intervention
- [ ] Tags created in readcast are usable as briefing source filters
- [ ] Auto-tagging on briefing ingest works via dense embeddings

---

### Phase C: Briefing Agent Enhancements (weeks 7-8)

**Goal:** Upgrade to real data sources and delivery. Gmail API replaces DOM scraper.

- [ ] Gmail API gatherer — OAuth installed-app flow, token stored in `~/.localknowledge/tokens/`
- [ ] Scope: `gmail.readonly` only (never send, never modify)
- [ ] Full email body access, thread context, label awareness
- [ ] Google Calendar gatherer (same OAuth flow, calendar.readonly)
- [ ] iMessage delivery — macOS Shortcuts/AppleScript automation
- [ ] Cross-source synthesis improvements — relate gathered items to existing knowledge base documents
- [ ] DOM scraper remains as fallback but is no longer the primary path

**Gate C — briefing quality validation:**
- [ ] Gmail API briefing covers full email content, not just subject lines
- [ ] Calendar integration adds "you have a meeting with X at 2 PM, and they emailed about Y" cross-referencing
- [ ] Daily briefing is genuinely useful for 2+ weeks of personal use

---

### Phase D: Spock MVP + Advanced Retrieval (weeks 9-12)

**Goal:** Third product on the substrate. Add ColBERT and graph embeddings now that there's enough cross-product data to justify them.

**D.1 — Spock core (weeks 9-10)**
- [ ] Create `packages/spock/` in monorepo
- [ ] Implement card generation from documents (7-type taxonomy, LLM-based)
- [ ] Implement FSRS algorithm
- [ ] Implement LLM grading — local Qwen for fast first-pass, Claude API for nuanced grading
- [ ] Implement voice session loop — Whisper STT → grade → kokoro-edge TTS feedback
- [ ] Implement CLI: `spock study --tag X`, `spock cards generate`, `spock stats`
- [ ] Implement document discovery — find unstudied material across all products by tag
- [ ] Spock MVP targets turn-based interaction (3-6s response OK), not real-time conversation

**D.2 — ColBERT backend (week 11)**
- [ ] Implement `ColBERTBackend` — mlx-colbert, token-level storage in sqlite
- [ ] Two-stage retrieval: dense first-pass → ColBERT MaxSim re-ranking
- [ ] Register in `EmbeddingRegistry`, opt-in via config
- [ ] Benchmark: ColBERT vs. dense-only for Spock's study material discovery

**D.3 — Graph embedding backend (week 11)**
- [ ] Implement `GraphBackend` — Node2Vec or spectral over document-tag bipartite graph
- [ ] Recompute on threshold of changes (50+ new documents since last computation)
- [ ] Register in `EmbeddingRegistry`, opt-in via config
- [ ] Benchmark: graph embeddings for cross-domain discovery (the "pharma job post relates to your orgo cards" scenario)

**D.4 — Tag relations (week 12)**
- [ ] Add `tag_relations` table (deferred from Phase A)
- [ ] Cross-cutting links: AI-governance relates_to politics, relates_to investments
- [ ] Graph embeddings can now traverse richer structure

**D.5 — Publish (week 12)**
- [ ] Publish `spock` 0.1.0
- [ ] Publish `localknowledge-core` 0.2.0 (new embedding backends, tag_relations)
- [ ] All products updated and tested against new core

**Gate D — full platform validation:**
- [ ] End-to-end: add article in readcast → auto-tagged → Spock generates cards → study session works
- [ ] End-to-end: briefing agent gathers gmail + calendar → synthesizes with readcast article context → audio delivered
- [ ] ColBERT measurably improves precision for Spock's material discovery vs. dense-only
- [ ] Graph embeddings surface cross-domain connections that text similarity misses
- [ ] Three products running concurrently against shared DB without corruption or contention
- [ ] Spock voice loop round-trip is under 6 seconds (STT + grade + TTS)

---

### Phase E: Optimization + Polish (weeks 13+)

- [ ] Paralinguistic analysis for Spock (confidence/hesitation from voice signal)
- [ ] Spock web dashboard (study stats, mastery progression)
- [ ] Per-product backend weight tuning in hybrid search
- [ ] sqlite-vec as a first-class accelerator once it reaches stable release
- [ ] Evaluate monorepo → multi-repo split based on release velocity needs
- [ ] Documentation: getting started, architecture guide, embedding backend development
- [ ] Future embedding backends: HyDE, SPLADE, Mountain Discovery feature extraction

---

## Open Questions

### Resolved

1. **Monorepo vs multi-repo** — **Decided: monorepo first.** Split after core API stabilizes and 2+ products are shipping. Cross-package refactors during extraction are too painful across repos.

2. **sqlite-vec** — **Decided: optional.** Dense backend uses numpy exact search by default, detects sqlite-vec at runtime and uses it opportunistically. No hard packaging dependency on a pre-v1 library.

3. **Hooks framework** — **Decided: no.** Direct database queries are the integration layer. Add hooks only when duplication across 3+ products becomes painful.

4. **Auth ownership** — **Decided: briefing-agent owns auth.** Core shouldn't know about Google OAuth. Tokens stored in `~/.localknowledge/tokens/` by convention.

5. **Briefing agent daemon model** — **Decided: launchd plist + CLI.** Not a custom always-on daemon. `briefing schedule start` generates a launchd plist. Fallback to cron for non-macOS.

6. **Tag relations** — **Decided: deferred to Phase D.** Parent/child hierarchy via `parent_id` ships in Phase A. Graph relations ship alongside graph embeddings when there's real cross-product usage to justify them.

### Still Open

7. **Package name**: `localknowledge-core` as distribution, `localknowledge` as import. This is descriptive and boring, which is correct for infrastructure. But if there's a name that better captures the "personal knowledge substrate" concept and isn't already taken on PyPI/anaconda.org, worth considering before 0.1.0 ships.

8. **Embedding model + MLX**: Dense default is all-MiniLM-L6-v2 (384d). Ship with sentence-transformers for broad compatibility, or go MLX-first since readcast and kokoro-edge are already Apple Silicon-only? The MLX path is faster and more aligned with local-first philosophy. Proposal: ship sentence-transformers as default, add MLX model support as a config option (`model = "mlx-community/all-MiniLM-L6-v2-mlx"`). Let the device config handle acceleration.

9. **Spock latency budget**: MVP targets turn-based (3-6s acceptable). But how much of that budget goes to STT vs. grading vs. TTS? Whisper on MLX should be sub-1s for short answers. kokoro-edge is known fast (~100ms). That leaves 2-5s for the LLM grading call. Local Qwen 3.5 4B should handle this on the 4090 or M-series, but needs benchmarking. The question is whether the grading quality from a 4B model is good enough or if Claude API is needed for most questions (adding network latency).

10. **Content chunking strategy**: For long documents (readcast articles, long emails), should we chunk before embedding or embed the full document? Chunking gives better retrieval precision but complicates the document model (`parent_document_id` already supports this). Proposal: defer chunking to Phase D, embed full documents in Phase A. Add chunking as an optional ingest step once retrieval quality issues are observed in practice.

11. **Readcast v1 backward compatibility**: How long do we maintain the old `~/.readcast/` config path and migration from the old DB? Proposal: readcast v2 auto-migrates on first run, keeps a `.v1.bak` backup. After v2.1.0, remove migration code and document manual migration for stragglers.
