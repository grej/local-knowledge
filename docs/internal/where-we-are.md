# Where We Are — 2026-03-26

## Project Overview

Local Knowledge is a macOS Apple Silicon app for personal knowledge management with TTS narration. Three repos:

- **local-knowledge** (`/Users/greg/Documents/dev/local-knowledge`) — monorepo: core, cli, ui, mcp, desktop (menu bar), app (Tauri). Published to anaconda.org/gjennings as `local-knowledge` v0.5.0.
- **readcast** (`/Users/greg/Documents/dev/transcriber`) — article capture, TTS synthesis, web UI. Published as `readcast` v0.3.0.
- **kokoro-mlx** (`/Users/greg/Documents/dev/kokoro-mlx`) — local TTS daemon (Swift/MLX). Published as `kokoro-edge` v0.1.1.

Both Python packages share `~/.localknowledge/store.db` (SQLite). readcast depends on localknowledge-core and kokoro-edge.

## Installation

Single command installs everything:
```bash
pixi global install --environment local-knowledge --channel gjennings --channel conda-forge \
  --expose lk --expose lk-mcp --expose lk-ui --expose lk-desktop \
  --expose readcast --expose kokoro-edge \
  local-knowledge readcast
```

Then `lk-desktop install` sets up launchd for start-on-login. Menu bar app supervises 4 services:
- kokoro-edge (TTS engine, port 7777)
- readcast (web UI, port 8765)
- lk-ui (knowledge base UI, port 8321)
- lk-mcp (MCP server for Claude, port 8322)

## Published Versions (as of 2026-03-26)

| Package | Version | Channel | Triggered by |
|---------|---------|---------|-------------|
| kokoro-edge | 0.1.1 | anaconda.org/gjennings | `git tag v*` in kokoro-mlx |
| local-knowledge | 0.5.0 | anaconda.org/gjennings | `git tag v*` in local-knowledge |
| readcast | 0.3.0 | anaconda.org/gjennings | `git tag v*` in transcriber |

Tauri app v0.5.0 built locally (DMG at `packages/app/target/release/bundle/dmg/`). No CI for Tauri yet.

## What Was Done — 2026-03-25/26 Session

### Playwright E2E Test Suite (readcast)
- Added 54 Playwright e2e tests across 10 test files
- Created test infrastructure: `playwright.config.ts`, `scripts/test-server.py` (starts FastAPI with isolated temp DB), `tests/e2e/seed.py` (seeds 8 articles + 4 lists)
- Coverage: layout, navigation, article list/detail, playlist, drawer, player, keyboard, search, drag-drop
- Added `data-testid` attributes to ~20 key UI elements
- Added `@playwright/test` + Chromium to dev dependencies
- Added `pixi run test:e2e` and `pixi run test:e2e:headed` tasks

### Audio Playback Fixes (readcast)
- Fixed `audio.src` comparison bug (relative vs absolute URL mismatch)
- Enriched `/api/lists/{id}/items` endpoint to include `audio_url`, `has_audio`, and `renditions` on each article
- Fixed prev/next track buttons to maintain playback state (was stopping audio on skip)

### Frontend Rewrite — Type-Based Navigation (readcast)
- **Replaced per-list nav sidebar** with 4 fixed type buttons in the rail: ⊙ All, ☐ Action, ◎ Collection, ♫ Playlist
- **Chooser view**: when a type has multiple lists, shows cards with icon, name, metadata, EQ bars for playing playlist
- **Removed right drawer**: replaced with queue peek popover (floating above player bar, ≡ button)
- **Speed control**: speed button in player bar + playlist hero, popover with presets (0.5×–2×), adjusted duration display
- **Undo toast system**: destructive actions show toast with Undo button, auto-dismiss 3.5s
- **List CRUD**: create modal with type grid + icon picker, edit mode (✎/✓), rename, delete with confirmation
- **List pill toggles**: detail panel pills are functional add/remove buttons with color states
- **Article metadata**: source URL as clickable link, author, publication, published date, word count
- **Orientation chips**: All Items shows due count, unnarrated count + Gen All button
- **Always-visible player bar** (Spotify model): auto-loads first playlist on mount, shows transport controls immediately
- **Layout fixes**: `#root` flex column, detail panel scroll (`overflow-y: scroll`, `-webkit-overflow-scrolling: touch`)

### Bundle & Build Fixes (readcast)
- Renamed `bundle.js` → `app.js` to break Brave's aggressive caching
- Updated `build-frontend.mjs`, `index.html`, `verify_distribution.py`, and API tests

### Tagged Releases
- local-knowledge v0.5.0: UX spec docs + prototype files
- readcast v0.3.0: type-nav refactor + Playwright tests + all fixes
- Tauri app v0.5.0: local DMG build

### Known Issues
- **kokoro-edge CI broken**: Swift build fails because MLXUtilsLibrary requires tools version 6.2.0 but the macos-15 GitHub runner has older Xcode. Existing v0.1.1 binary works fine. Fix: pin older MLXUtilsLibrary or wait for runner update.
- **Tauri app not in CI**: no automated DMG distribution yet. Local build only.
- **Playwright tests need updating**: the e2e tests were written for the old nav sidebar + drawer architecture. They pass for the Playwright test server (which has its own seed data) but the test assertions reference removed components like `nav-sidebar`. Needs a test rewrite pass.

## Key Files

| File | What |
|---|---|
| `transcriber/src/readcast/web/frontend/app.jsx` | React frontend (~1250 lines, rewritten) |
| `transcriber/src/readcast/web/static/app.js` | Built bundle |
| `transcriber/src/readcast/core/store.py` | SQLite store: lists, items, renditions |
| `transcriber/src/readcast/api/app.py` | FastAPI endpoints |
| `transcriber/src/readcast/services.py` | Business logic + ProcessingWorker |
| `transcriber/tests/test_api.py` | API tests (109 passing) |
| `transcriber/tests/e2e/` | Playwright e2e tests (54, need updating) |
| `transcriber/playwright.config.ts` | Playwright configuration |
| `transcriber/recipe/recipe.yaml` | Conda recipe (requires local-knowledge >=0.5.0) |
| `local-knowledge/packages/app/tauri.conf.json` | Tauri app config (v0.5.0) |
| `local-knowledge/next-steps-24-mar/spec.md` | Implementation spec |
| `local-knowledge/docs/internal/where-we-are.md` | This file |

## Running Tests

```bash
# Backend tests (109 passing)
cd transcriber && pixi run test

# E2E tests (need updating for new nav)
cd transcriber && pixi run test:e2e

# Lint
cd transcriber && pixi run lint
```

## Next Steps

1. **Fix Playwright e2e tests** for the new type-nav architecture (rail buttons, chooser, queue peek)
2. **Fix kokoro-edge CI** — pin MLXUtilsLibrary or update Xcode requirement
3. **Add Tauri CI** — GitHub Actions workflow for automated DMG builds on tag push
4. **Consider**: isNew indicator, smart sort, drag-to-reorder in playlist view
