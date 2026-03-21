# local-knowledge

Local-first personal knowledge engine for macOS. One install gives you a shared knowledge
base, hybrid search, a web UI, CLI, MCP server for Claude, and a menu bar app that manages
everything.

## Install

```bash
pixi global install local-knowledge --channel gjennings --channel conda-forge
```

This installs all commands into an isolated environment. No Python, no dependencies to
manage — just the commands.

## Getting started

```bash
lk-desktop
```

A menu bar icon appears. All services start automatically — click **Readcast** or
**Knowledge Base** to open their web UIs in your browser. The menu bar shows health
status for each service and auto-restarts anything that crashes.

To start on login: click the menu bar icon → **Start on Login**.

## What's included

| Command | What it does |
|---------|-------------|
| `lk-desktop` | Menu bar app — starts and monitors all services |
| `lk` | CLI — add documents, search, manage tags and projects |
| `lk-ui` | Web UI at `http://127.0.0.1:8321` — browse and search your knowledge base |
| `lk-mcp` | MCP server — gives Claude (and other LLM tools) access to your knowledge base |

## MCP server for Claude Desktop

The MCP server runs on `http://localhost:8322` (started automatically by `lk-desktop`).
Add this to your `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "local-knowledge": {
      "url": "http://localhost:8322/sse"
    }
  }
}
```

The MCP server exposes these tools to Claude:

- **search** — hybrid full-text + semantic search across all documents
- **find_connections** — discover semantically related documents
- **get_context** — full context for a project (documents, topics, related projects)
- **ingest** — add text to the knowledge base
- **list_projects** — list projects with document counts and topics
- **tag** / **suggest_projects** — manage document metadata
- **refresh_project_context** — recompute project embeddings

## Products

Local Knowledge is a shared core that multiple products build on. Each product writes to
the same database at `~/.localknowledge/store.db`, so everything is cross-searchable.

- **[readcast](https://github.com/grej/readcast)** — captures web articles, auto-tags them,
  builds a knowledge graph, and generates audio podcasts via local TTS
- **Spock** *(coming soon)* — voice-first mastery tutor with spaced repetition

## Architecture

```
packages/
├── core/       localknowledge-core  — database, embeddings, search engine
├── cli/        lk-cli               — click CLI (lk command)
├── ui/         lk-ui                — FastAPI web interface
├── mcp/        lk-mcp               — MCP server (stdio transport)
├── desktop/    lk-desktop           — macOS menu bar app + service supervisor
└── readcast/   readcast-v2          — readcast adapter layer
```

All data lives in `~/.localknowledge/`:

- `store.db` — SQLite database (documents, embeddings, tags, knowledge graph)
- `config.toml` — configuration for all products
- `logs/` — service logs (managed by lk-desktop)

## Requirements

- macOS 15+, Apple Silicon

## Development

```bash
git clone https://github.com/grej/local-knowledge.git
cd local-knowledge
pixi install
pixi run test
pixi run lint
```

## License

MIT
