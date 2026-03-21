# Local Knowledge — Where We Are

## What This Is

A local-first knowledge management platform that stores documents, embeds them for semantic search, and provides hybrid search (FTS + embeddings). Runs entirely on-device using MLX on Apple Silicon. No cloud dependencies.

There's also a sibling project, **Readcast** (at `../transcriber/`), that turns web articles into podcast audio. Readcast uses Local Knowledge as its core storage and search layer.

## Architecture

Monorepo with 4 packages:

```
packages/
  core/     — localknowledge-core: storage, embeddings, search, tags, config
  cli/      — lk-cli: Click CLI wrapping KnowledgeService
  ui/       — lk-ui: FastAPI web UI (just built, minimal)
  readcast/ — readcast-v2: legacy v1→v2 migration compat
```

**Runtime stack:** Python 3.12, SQLite (WAL mode), MLX for embeddings, pixi for env management.

### Core Layer

`KnowledgeService` is the facade. Everything goes through it:

| Capability | How it works |
|---|---|
| **Storage** | SQLite via `Database` class. Documents, artifacts, tags tables. Migration system (currently v001 initial + v002 chunk embeddings). |
| **Search (FTS)** | SQLite FTS5 virtual table on title/content/summary. |
| **Search (Semantic)** | `DenseBackend` embeds text via mlx-embeddings, stores vectors as BLOBs. Cosine similarity at query time. |
| **Search (Hybrid)** | `HybridSearch` combines FTS + semantic via Reciprocal Rank Fusion (RRF). |
| **Chunking** | `chunk_text()` splits on paragraph boundaries with overlap. Each chunk gets its own embedding. Search scores per-chunk, aggregates max per document. |
| **Tags** | Hierarchical tags with confidence scoring. AND/OR intersection queries. |
| **Config** | TOML at `~/.localknowledge/config.toml`. Sections: database, tts, llm, embeddings. |

### Embedding System

- **Current model:** `BAAI/bge-small-en-v1.5` (384 dimensions, ~33M params)
- **Also tested:** `BAAI/bge-large-en-v1.5` (1024 dimensions, ~335M params)
- Model is configurable via `embeddings.model` in config
- `DenseBackend` accepts an `embed_fn` callable for testing/swapping
- Model cache is keyed by model name (can load multiple models simultaneously)
- Search queries filter by `WHERE model = ?` to prevent mixed-model garbage
- Schema stores: document_id, chunk_index, chunk_text, chunk_start, chunk_end, embedding (BLOB), model, created_at

### What Readcast Uses From Core

Readcast's `embedder.py` is a thin shim that calls core's `DenseBackend.embed_document_chunked()` and `find_similar_by_text()`. Readcast's `store.py` delegates embedding storage to core's `embeddings_dense_v2` table. The old readcast-specific `embeddings` table has been removed.

## Test Coverage

**107 fast tests** (`pixi run test`):
- Core: 71 tests (documents, tags, embeddings, chunker, service, config, db, artifacts, integration, LLM, TTS)
- CLI: 28 tests
- Readcast compat: 8 tests

**17 slow tests** (`pixi run test:slow`, require real MLX model loading):
- `test_embeddings_real.py` — 3 tests: semantic search groups topics correctly
- `test_search_quality.py` — 12 tests: 10-doc corpus, similarity/semantic/hybrid/chunk/tag queries
- `test_model_comparison.py` — 2 tests: BGE-small vs BGE-large side-by-side with MRR/Recall@3 metrics

**72 transcriber tests** (`cd ../transcriber && pixi run test`):
- Full readcast stack: API, CLI, services, store, embedder, synthesizer, extractor, chunker, config, models

## UI State

`pixi run ui` starts a FastAPI server on port 8321. Single-page vanilla HTML/JS app with:
- Document browse and search (hybrid/semantic/fts + chunk mode)
- Document detail view with tags and content
- Add document form
- Tag documents
- Delete documents

It works but is minimal — no auth, no pagination, no real-time updates.

## Model Comparison Results

Ran 5 queries against the 10-document corpus with both models:

```
Summary: bge-small-en-v1.5 wins 0, bge-large-en-v1.5 wins 0, ties 5
```

Both models perform identically on straightforward queries. The differences would emerge with harder/ambiguous queries or for tag classification tasks (embedding a tag concept like "energy" and classifying documents against it).

## Key Files

| File | Purpose |
|---|---|
| `core/src/localknowledge/service.py` | KnowledgeService facade |
| `core/src/localknowledge/embeddings/dense.py` | DenseBackend — embed, search, model management |
| `core/src/localknowledge/embeddings/hybrid.py` | HybridSearch — RRF fusion of FTS + semantic |
| `core/src/localknowledge/chunker.py` | Paragraph-boundary text chunking with overlap |
| `core/src/localknowledge/documents.py` | DocumentStore — CRUD, FTS5, content-hash dedup |
| `core/src/localknowledge/tags.py` | TagStore — hierarchical tags, AND/OR queries |
| `core/src/localknowledge/config.py` | TOML config system |
| `core/src/localknowledge/db.py` | SQLite connection + migration runner |
| `core/src/localknowledge/models.py` | Document, SearchResult, ChunkResult dataclasses |
| `cli/src/lk/cli.py` | Click CLI commands |
| `ui/src/lk_ui/app.py` | FastAPI web UI |
| `pixi.toml` | Workspace config, tasks, dependencies |

## What's Not Built Yet

- **Auto-tagging:** User declares a tag concept, system classifies documents against it using embeddings (or LLM for borderline cases). The infrastructure is ready (tags, embeddings, chunk search) but the classification logic doesn't exist.
- **Ingestion from sources:** Core only supports adding text/files. No web scraping, no RSS, no API integrations. (Readcast has web extraction but it's readcast-specific.)
- **Document updates/versioning:** Documents are immutable after creation (except soft-delete). No edit-and-re-embed flow in core.
- **Multi-user / auth:** Everything is single-user local.
- **Better embedding models:** Tested BGE-small and BGE-large. Haven't explored nomic-embed, GTE, or other model families that might be better for classification tasks.
