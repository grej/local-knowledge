# local-knowledge

Local-first personal knowledge engine with hybrid search (FTS5 + vector) and MCP server.

## Installation

```bash
pixi global install local-knowledge \
  -c https://conda.anaconda.org/gjennings \
  -c https://repo.anaconda.com/pkgs/main \
  -c conda-forge
```

Or with conda directly:

```bash
conda install -c gjennings -c conda-forge local-knowledge
```

## Quick Start

```bash
# Add a document
lk add "https://example.com/article"

# Search your knowledge base
lk search "distributed systems"

# Launch the web UI
lk-ui

# Start the MCP server (for Claude, etc.)
lk-mcp
```

## Features

- **Hybrid search** — full-text (SQLite FTS5) + dense vector embeddings
- **Local-first** — all data stays in a local SQLite database
- **MCP server** — expose your knowledge base to LLM assistants
- **Web UI** — browse, search, and manage documents
- **CLI** — fast command-line interface for all operations
- **Monorepo** — modular packages that share a common core

## Architecture

```
packages/
├── core/       localknowledge-core  — database, embeddings, search
├── cli/        lk-cli               — click-based CLI (lk command)
├── ui/         lk-ui                — FastAPI web interface
├── mcp/        lk-mcp               — MCP server for LLM tools
└── readcast/   readcast-v2          — article reader (separate product)
```

## Requirements

- Python 3.12+
- Apple Silicon Mac for embedding generation (mlx-embeddings, dev-only)

## Development

```bash
pixi install
pixi run test
pixi run lint
```

## License

MIT
