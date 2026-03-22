# AGENTS.md

## Project overview

Local Knowledge is a local-first personal knowledge engine for macOS (Apple Silicon).
Monorepo with 6 packages sharing a SQLite database at `~/.localknowledge/store.db`.

Installed via `pixi global install local-knowledge --channel gjennings --channel conda-forge`.
Primary entry point is `lk-desktop` (menu bar app that manages all services).

## Packages

| Package | Location | Entry point | Purpose |
|---------|----------|-------------|---------|
| `localknowledge-core` | `packages/core/` | (library) | Database, embeddings, search, config, migrations |
| `lk-cli` | `packages/cli/` | `lk` | Click CLI for all operations |
| `lk-ui` | `packages/ui/` | `lk-ui` | FastAPI web UI on port 8321 |
| `lk-mcp` | `packages/mcp/` | `lk-mcp` | MCP server (stdio for Claude Desktop, SSE on port 8322 for Claude Code) |
| `lk-desktop` | `packages/desktop/` | `lk-desktop` | macOS menu bar app + service supervisor |
| `readcast-v2` | `packages/readcast/` | (library) | Adapter mapping readcast's article API onto core |

## Development commands

```bash
pixi install          # install all deps + editable packages
pixi run test         # pytest (skips slow tests)
pixi run test:slow    # pytest slow tests only (embedding model, etc.)
pixi run lint         # ruff check .
```

## Testing

- Framework: pytest
- Marker: `@pytest.mark.slow` for tests that load ML models or do network I/O
- Each package has its own `tests/` directory
- Fixtures: `base_dir` (tmp_path), `db` (Database instance) — defined in per-package conftest.py
- Run from repo root: `pixi run test`

## Architecture

- **Config**: `~/.localknowledge/config.toml` — TOML with typed sections (`[database]`, `[tts]`, `[llm]`, `[embeddings]`) plus arbitrary product sections via `product_config(name)`
- **Database**: SQLite + WAL mode, migration system in `packages/core/src/localknowledge/migrations/`
- **Search**: Hybrid FTS5 + dense vector embeddings, fused via Reciprocal Rank Fusion
- **Embeddings**: `packages/core/src/localknowledge/embeddings/` — MLXEmbedder (Apple Silicon), chunking, indexing
- **MCP server**: FastMCP with two transports. SSE on port 8322 is the default (managed by lk-desktop, used by Claude Code). `--stdio` flag for Claude Desktop which spawns its own subprocess. Both share the same SQLite database. Tools defined in `packages/mcp/src/lk_mcp/tools.py`

## Build and release

- Build system: hatchling (all packages)
- Conda recipe: `recipe/recipe.yaml` — rattler-build, published to anaconda.org/gjennings
- CI: `.github/workflows/publish-conda.yml` — triggered by `v*` tag push, runs on macos-15
- Version: extracted from git tag (`v0.3.0` → `0.3.0`), not from pyproject.toml

## Key conventions

- Python 3.12+, macOS 15+, Apple Silicon only
- All packages use `src/` layout with hatchling
- `__init__.py` files contain only docstrings — no `__version__` variables
- Dependencies managed via pixi (conda) — never raw pip
- Internal architecture docs live in `docs/internal/` (not published)
