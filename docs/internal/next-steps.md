# Local Knowledge — Next Steps

## The Big Picture

The goal is a **local-first knowledge platform** that helps you organize, find, and understand your documents — entirely on-device. The current system can store documents, embed them, and search them. The next meaningful step is making it *smart* — automatically classifying documents and surfacing connections, using the embedding infrastructure we've built.

## Candidate Next Steps

### 1. Embedding-Based Auto-Tagging

**The idea:** User declares a tag (e.g., "energy"). System embeds the tag name/description, scores all documents' chunks against it via cosine similarity, and auto-tags above a threshold. Borderline cases could be flagged for user review (active learning loop).

**Why now:** Tags exist, chunk embeddings exist, the model comparison infrastructure exists. This is the natural next use of embeddings beyond search.

**Open questions:**
- Is embedding the tag *name* enough, or does the user need to provide a description/exemplar?
- What threshold separates "definitely this tag" from "ask the user"?
- Should confirmed/rejected decisions refine the tag's embedding (average in confirmed doc embeddings)?
- Should this run on every new document automatically, or be a batch operation?

### 2. Better Embedding Models for Classification

**The idea:** BGE-small/large are good at search but were trained for retrieval, not classification. Models like nomic-embed-text-v1.5 or GTE variants might perform better at "is this document *about* X?" discrimination.

**Why now:** The model comparison test infrastructure is built. Adding a new model to the comparison is a config change + one line in the test.

**What to evaluate:** Run the same corpus through 3-4 models, but add classification-style queries: "is this document about energy?" → measure whether energy docs score significantly higher than non-energy docs (separation/gap), not just whether they rank first.

### 3. Smarter Ingestion

**The idea:** Add documents from URLs, files, or directories — not just pasted text. Core could have a simple extractor that handles HTML, Markdown, PDF, plain text.

**Why now:** Readcast already has a sophisticated extractor (`readcast/core/extractor.py`) that handles URLs, HTML (via readability), and plain text. Some of this could be ported to core for general use.

### 4. Document Relationships / Knowledge Graph

**The idea:** Use embeddings to find connections between documents. "These 3 documents all discuss battery technology." Could be explicit (LLM-extracted entities/relationships like readcast's tagger) or implicit (cluster documents by embedding similarity).

**Why now:** Readcast already has entity/relationship extraction via LLM. The core tags system supports hierarchical tags. The chunk-level embeddings could power clustering.

### 5. UI Polish

**The idea:** The web UI works but is bare-minimum. Could add: tag management view, embedding status/progress, model switching from UI, search comparison view (side-by-side FTS vs semantic), document editing.

**Why now:** The API endpoints all exist. It's purely frontend work.

### 6. MCP Server

**The idea:** Expose Local Knowledge as an MCP (Model Context Protocol) server so LLMs like Claude can search and retrieve documents from your knowledge base during conversations.

**Why now:** The service layer is clean and API-ready. MCP is the natural way to make local knowledge accessible to AI assistants.

## Recommended Sequence

**Phase 1: Auto-tagging** (builds on everything we just shipped)
1. Implement embedding-based tag classification
2. Add classification-specific tests to the model comparison suite
3. Add auto-tag CLI command and UI button
4. Evaluate whether BGE is sufficient or we need a better model for this task

**Phase 2: Smarter ingestion** (makes the system useful for real workflows)
1. Port URL/HTML extraction from readcast to core
2. Add `lk add --url` and UI URL input
3. Directory watching / batch import

**Phase 3: MCP server** (makes the knowledge base accessible to AI)
1. Expose search, document retrieval, and tagging via MCP
2. Enable Claude to query your local knowledge during conversations

## Technical Debts / Cleanup

- `EmbeddingsConfig.dimensions` is informational-only but displayed in config. Should auto-update when model changes.
- `embedding_stats()` does a full table scan (`list(limit=100000)`). Should use COUNT queries.
- No pagination in document list APIs.
- Readcast's `embedder.py` still has its own `hybrid_search` implementation instead of using core's `HybridSearch` directly (it delegates for semantic but reimplements RRF).
- The model comparison test showed BGE-small and BGE-large are identical on simple queries. Need harder queries or a classification task to see real differences.
