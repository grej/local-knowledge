# Where We Are — 2026-03-25

## Project Overview

Local Knowledge is a macOS Apple Silicon app for personal knowledge management with TTS narration. Two repos:

- **local-knowledge** (`/Users/greg/Documents/dev/local-knowledge`) — monorepo: core, cli, ui, mcp, desktop (menu bar), app (Tauri). Published to anaconda.org/gjennings as `local-knowledge` v0.4.0.
- **readcast** (`/Users/greg/Documents/dev/transcriber`) — article capture, TTS synthesis, web UI. Published as `readcast` v0.2.0.

Both share `~/.localknowledge/store.db` (SQLite). readcast depends on localknowledge-core.

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

## Current State of the UX Rewrite

We're implementing a major UX overhaul based on the spec at `next-steps-24-mar/spec.md` and the HTML prototype at `next-steps-24-mar/local-knowledge-new-proposed-interface.html`.

### What's Done

**Backend (fully working, 109 tests passing):**
- `lists` table: user-defined collections, todos, playlists (seeded with 5 test lists)
- `list_items` join table: docs in lists with position, due dates, done state
- Renditions system: get/set/clear renditions on document metadata, backwards-compatible with old audio fields
- API endpoints: lists CRUD, list items CRUD with reorder, renditions (audio/summary/audio_summary), batch narrate
- Article serialization includes `renditions` and `list_memberships`
- List items endpoint now enriches articles with `audio_url`, `has_audio`, and `renditions`
- Tags seeded on documents from `document_tags` table

**Frontend (app.jsx, ~2060 lines — fully implemented):**

All 6 spec steps complete:
- Three-panel layout: nav (210px) + center (370px) + detail (flex:1)
- Collapsible nav with icon rail (36px) — `[` key toggles
- Nav sections: "Knowledge base" with "All items", "Action items" (todos), "Lists" (collections/playlists)
- Center panel: doc list with audio icons, tag pills, list badges, right-gutter actions
- Playlist hero view: icon, name, stats, "Play all" + hamburger buttons, tracklist
- Detail panel: header, rendition bar, list assignment toggles, body text
- Right drawer (queue controller): 280px slide-in, playlist selector, track list
- Bottom bar: transport controls, track info, progress bar, queue toggle
- Audio playback wired to real audio file URLs from renditions
- Keyboard shortcuts (`[` nav, `]` drawer, Space play/pause, `/` search, arrows navigate)
- Drag-and-drop reorder in playlist and drawer
- Popovers for list assignment and playlist picker
- `data-testid` attributes on ~20 key elements for Playwright testing

**Playwright E2E Tests (54 tests passing):**
- Layout: three-panel rendering, panel widths, dark background
- Navigation: list selection, playlist hero, nav collapse/expand, keyboard `[`
- Article list: rendering, audio icons, tag pills, clicking updates detail
- Article detail: title, tags, list memberships, body text loading
- Playlist: hero section, Play All, tracklist, narration banner, now-playing
- Drawer: open/close, track list, playlist selector, keyboard `]`
- Player: bottom bar visibility, track title/position, next/prev, audio src, progress bar
- Keyboard: `[`, `]`, Space, `/`, ArrowDown
- Search: filtering, clearing, `/` focus
- Drag-and-drop: handles, draggable items, reorder

### Fixed Issues (this session)

1. **Browser cache bust** — Renamed `bundle.js` to `app.js` to break Brave's aggressive caching of the old bundle. Removed query-string cache bust.

2. **Audio src comparison bug** — Fixed `audio.src !== item.article.audio_url` (absolute vs relative URL mismatch) to use `!audio.src.endsWith(item.article.audio_url)`.

3. **List items missing audio_url** — The `/api/lists/{id}/items` endpoint was returning raw article data without `audio_url` or `renditions`. Fixed to enrich each article with `audio_url`, `has_audio`, and `renditions`.

### Data State

- 23 documents in `~/.localknowledge/store.db`
- 5 lists seeded: "Respond To" (todo, 4 items), "Study Psychology" (collection, 3), "Geopolitics Deep Dive" (collection, 5), "Morning Commute" (playlist, 5), "AI Tools to Evaluate" (collection, 2)
- Tags seeded on ~17 documents
- 19 articles have audio files, 4 don't

### Architecture

```
body (flex-direction: column)
├── #app (display: flex; flex: 1; overflow: hidden)
│   ├── .nav-rail (36px, only when collapsed)
│   ├── .nav (210px, collapsible to width:0)
│   ├── .center (370px, flex column, overflow:hidden)
│   │   ├── header (flexShrink:0)
│   │   ├── search (flexShrink:0)
│   │   └── doc-list (flex:1, overflow-y:auto, minHeight:0)
│   ├── .detail-wrap (flex:1, display:flex)
│   │   ├── .detail (flex:1, overflow-y:auto, minWidth:0)
│   │   └── .drawer (width:0 or 280px, transition)
├── #bbar-container (flexShrink:0)
│   └── .bbar (50px, when playlist loaded)
```

### Key Files

| File | What |
|---|---|
| `transcriber/src/readcast/web/frontend/app.jsx` | React frontend (~2060 lines) |
| `transcriber/src/readcast/web/static/app.js` | Built bundle (was bundle.js) |
| `transcriber/src/readcast/core/store.py` | SQLite store: lists, items, renditions |
| `transcriber/src/readcast/api/app.py` | FastAPI endpoints |
| `transcriber/src/readcast/services.py` | Business logic + ProcessingWorker |
| `transcriber/tests/test_api.py` | API tests (109 passing) |
| `transcriber/tests/e2e/` | Playwright e2e tests (54 passing) |
| `transcriber/tests/e2e/seed.py` | Test data seeder |
| `transcriber/playwright.config.ts` | Playwright configuration |
| `transcriber/scripts/test-server.py` | E2E test server with temp DB |
| `local-knowledge/next-steps-24-mar/spec.md` | Implementation spec |
| `local-knowledge/next-steps-24-mar/local-knowledge-new-proposed-interface.html` | Visual prototype |

### Running Tests

```bash
# Backend tests (109 passing)
pixi run test

# E2E tests (54 passing)
pixi run test:e2e          # headless
pixi run test:e2e:headed   # watch in browser
```

### Next Steps

1. **Manually verify in Safari** — Open `pixi run start`, confirm scrolling works, drawer toggles, audio plays
2. Tag and publish next version
3. Consider adding CI integration for Playwright tests
