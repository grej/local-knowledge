# Playlist & Audio Player Integration — Implementation Guide

**Date:** 2026-03-25  
**Reference prototype:** `next-steps/local-knowledge-final.html`  
**Depends on:** `next-steps/LIST_UX_SPEC.md` (the base list system spec)

---

## Overview

This document specifies how to integrate audio playback, playlists, and a persistent player into the Local Knowledge app. The reference HTML prototype is a fully working demo — open it in a browser to see every interaction described here.

**Read the prototype HTML carefully.** It contains the exact CSS values, component structure, layout math, and interaction logic. This document explains the *why* and *what*; the prototype shows the *how*.

---

## Architecture Summary

```
┌─────────┬────────────────────┬──────────────────┬─────────┐
│ Nav     │ Center panel       │ Detail panel     │ Drawer  │
│ 210px   │ 370px              │ flex:1           │ 280px   │
│ (or     │                    │ (compresses when │ (slides │
│ 36px    │                    │  drawer opens)   │  in/out)│
│ rail)   │                    │                  │         │
├─────────┴────────────────────┴──────────────────┴─────────┤
│ Bottom bar — persistent player transport (50px)           │
└───────────────────────────────────────────────────────────┘
```

Key layout rules:
- The bottom bar sits OUTSIDE the main flex container. It spans full width, always at the bottom.
- The drawer is INSIDE the detail-wrap flex container, alongside the detail panel. When it opens (width: 0 → 280px), the detail panel compresses. No blur, no overlay.
- The nav can collapse to a 36px icon rail. When collapsed, the center + detail expand.

---

## 1. Player State

Add to the app's React state (or equivalent state store):

```typescript
interface PlayerState {
  playlistId: string | null;   // which playlist is currently loaded
  currentIndex: number;        // index into that playlist's items array
  playing: boolean;
  position: number;            // seconds into current track
}
```

This is session-level state — persist to localStorage for session recovery, but NOT to the database. The player state represents "what's playing right now," not saved data.

### Default state
```json
{ "playlistId": null, "currentIndex": 0, "playing": false, "position": 0 }
```

When `playlistId` is null, no playlist is loaded and the bottom bar is hidden.

---

## 2. Bottom Bar (Persistent Player)

**When visible:** Whenever `playerState.playlistId` is not null (a playlist is loaded).

**Structure (left to right):**
1. Transport controls: ⏮ (previous), ▶/▐▐ (play/pause toggle), ⏭ (next)
2. Info block (flex:1):
   - Title of currently playing doc (11px, weight 500, single line ellipsis)
   - Subtitle: playlist icon + name (clickable — navigates to that playlist in center panel) + "· 3/5" track position
   - Progress bar (3px height, clickable for seeking)
3. Time display: "3:42 / 10:20" in JetBrains Mono
4. Queue button (≡): toggles the right drawer open/closed. Highlighted when drawer is open.

**CSS:** Height 50px, background `var(--bg1)`, border-top 1px solid `var(--br)`. Play button is round, accent color. Skip buttons are transparent with muted text.

**Audio integration:** Wire transport controls to the kokoro-edge audio element. The progress bar position updates from `<audio>` element's `timeupdate` event. Seeking sets `audio.currentTime`. Track advancement on `ended` event moves to next track in playlist.

---

## 3. Right Drawer (Queue Controller)

**When available:** Whenever a playlist is loaded (playerState.playlistId is not null).

**Toggle:** Clicking the ≡ button on the bottom bar, or pressing a keyboard shortcut.

**Behavior:** The drawer has `width: 0` when closed, `width: 280px` when open, with `transition: width 0.2s ease`. The detail panel has `flex: 1` and `min-width: 0`, so it compresses naturally. No blur, no overlay, no absolute positioning.

**Structure (top to bottom):**

### Drawer header
- **Playlist selector dropdown** — an HTML `<select>` element listing ALL playlists (type === "playlist"). Changing the selection switches which playlist the drawer displays AND loads it into the player. Style the select to look native to the dark theme (transparent background, no default browser styling).
- Item count + total duration in JetBrains Mono
- Close button (✕)

### Track list (scrollable)
Each item shows:
- Track number (or ▶ if currently playing)
- Drag grip handle (⠿) — **must be functional** (see Drag & Drop section below)
- Track title (ellipsis on overflow)
- Duration in JetBrains Mono
- Remove button (×) — appears on hover

Currently-playing item has subtle blue background tint.

### Footer
- "Add current doc" button — adds whatever doc is selected in the center/detail panels to this playlist

---

## 4. Drag-and-Drop Reorder

Drag-and-drop MUST work in both the drawer track list AND the playlist center panel view. Implementation:

### State
```typescript
let dragState = { listId: string | null, fromIndex: number | null };
```

### Events on each draggable item
```
draggable="true"
ondragstart → set dragState, set opacity 0.3 on source
ondragover → preventDefault, show insertion indicator (border-top: 2px solid accent)
ondragend → reset opacity on all items, clear indicators
ondrop → reorder the list's items array, adjust playerState.currentIndex if needed
```

### Reorder logic
When dropping item from index `from` to index `to`:
1. Remove item from `from` position
2. Insert at `to` position (adjust for shift if `to > from`)
3. If the active playlist is being reordered, update `playerState.currentIndex`:
   - If the dragged item WAS the playing item: new index = drop position
   - If dragged from before playing item to after: playing index decrements
   - If dragged from after playing item to before: playing index increments
4. Persist the new order via `PUT /api/lists/{id}/items/reorder`

---

## 5. Playlist Center Panel View

When a playlist-type list is selected in the nav sidebar, the center panel renders a DIFFERENT view from the standard doc list.

### Hero section (top)
- Playlist icon (large, in a gradient-background rounded square)
- Playlist name (15px, bold)
- Stats: "5 items · 34:20"
- "▶ Play all" button (accent color) — loads this playlist into the player and starts from track 1

If this playlist is currently loaded in the player, ALSO show:
- "Now playing" label
- Currently playing track title
- Inline transport controls (prev, play/pause, next) + progress bar + time

### Narration banner (conditional)
If any items in the playlist lack audio renditions, show an amber banner:
"⚠ 2 items need narration [Generate all]"

The "Generate all" button triggers batch narration via `POST /api/lists/{id}/batch-narrate`.

### Track list
Same structure as the drawer track list but with more horizontal space:
- Track number / ▶ indicator
- Drag grip handle (functional)
- Audio state badge (♫ blue = ready, ✕ red = missing, ◌ amber = generating)
- Title + tag pills + source
- Duration
- Remove button (× on hover)

---

## 6. Doc-Level Audio Actions

These actions appear on doc rows when browsing ANY list view (All Items, collections, etc.) — NOT on playlist views (which have their own rendering).

### Right gutter column
A narrow column (3 stacked small buttons) on the right edge of every doc row. Always visible, never overlapping the title text. There is sufficient lateral space for these.

Buttons (top to bottom):
1. **▶ Play now** — only shown if doc has audio ready. Inserts into the current playlist after the current track and starts playing it.
2. **⊕ Add to queue** — only shown if doc has audio ready. Appends to the end of the current playlist. Shows ☑ in accent color if already in the active playlist.
3. **☰ Add to list** — always shown. Opens the add-to-list popover (shows ALL list types).

Each button shows a tooltip on hover (positioned to the left of the button).

### Audio icon play-on-hover
The audio indicator icon (♫) on each doc row transforms into a ▶ play button on hover (for docs with audio ready). CSS: absolute-positioned overlay on the icon that shows on `.dr:hover .aud-icon.ready .hover-play`.

---

## 7. Playlist Picker (🎧 ▾ button)

In the detail panel's rendition bar, when a doc has audio ready, there's a split button:
- Left side: "+ Queue" / "✓ Queued" — adds to the currently-loaded playlist
- Right side: "🎧 ▾" — opens a **playlist-specific popover**

The playlist picker popover ONLY shows lists with `type === "playlist"` (not collections or todos). Each item shows:
- Playlist icon + name
- "needs audio" warning if the doc lacks audio
- Checkmark if the doc is already in that playlist
- Clicking toggles membership

At the bottom: "+ New playlist" option.

This is DIFFERENT from the general "Add to list" popover (☰ button) which shows ALL list types.

---

## 8. Collapsible Nav Sidebar

The nav sidebar can collapse to a 36px icon rail.

### Expanded state (default, width: 210px)
- Header: green dot + "Local Knowledge" + collapse button (◂) on the right
- Collapsible sections: "Knowledge base", "Action items", "Lists" — each with a chevron toggle
- Full list items with icon, name, type badge, count

### Collapsed state (width: 0, replaced by 36px rail)
- The full nav div gets `width: 0; overflow: hidden` with a CSS transition
- A separate 36px rail div appears, showing:
  - ☰ button at top (click to expand back)
  - Separator
  - One icon button per list (⊙ for All, then each list's emoji icon)
  - Active list is highlighted with its color/bg

### Toggle
- Click ◂ button in nav header to collapse
- Click ☰ in the rail to expand
- Keyboard shortcut: `[`

CSS transition on `width` makes it smooth. The center and detail panels have `flex: 1` or fixed widths, so they expand into the freed space.

---

## 9. Playlist Audio Constraint

Playlists require audio renditions. When adding a doc to a playlist:

1. If doc has `audio.state === "ready"` → add normally
2. If doc has no audio → show a prompt: "This item needs audio narration. Generate now?" with [Generate] and [Cancel] buttons
3. If doc audio is generating → add it, show ◌ state in the playlist. It will update to ♫ when generation completes.

Enforce this in both the frontend (show warning in popovers) and the backend (API validation on `POST /api/lists/{id}/items` when list type is playlist).

---

## 10. Implementation Order

Given that the base list system from LIST_UX_SPEC.md is already partially implemented:

### Step 1: Player state + bottom bar
- Add PlayerState to React state/context
- Create the BottomBar component
- Wire to the existing `<audio>` element
- Transport controls: play/pause/prev/next
- Progress bar with seeking
- Track advancement on audio end

### Step 2: Right drawer
- Create Drawer component inside the detail-wrap flex container
- Toggle via bottom bar ≡ button
- Render current playlist's items
- Playlist selector dropdown in header
- Remove item functionality

### Step 3: Drag-and-drop in drawer + playlist view
- Implement dragStart/dragOver/dragEnd/drop handlers
- Wire to both drawer items and playlist center panel items
- Persist reorder via API

### Step 4: Playlist center panel view
- Detect when active nav item is a playlist type
- Render hero section with Play All button
- Render inline transport when this playlist is playing
- Narration banner + batch generate
- Track list with audio state indicators

### Step 5: Doc-level audio actions
- Add right gutter column to doc rows (play, queue, add-to-list)
- Audio icon hover-to-play overlay
- Playlist picker popover (🎧 ▾) in detail panel
- General add-to-list popover (☰) on doc rows

### Step 6: Collapsible nav
- Add navCollapsed state
- Create icon rail component
- CSS transitions on nav width
- Keyboard shortcut [

---

## 11. CSS Reference

All values come from the existing design tokens. Do NOT introduce new colors.

### Bottom bar
```css
height: 50px;
background: var(--bg1);  /* #0c0d12 */
border-top: 1px solid var(--br);  /* #222538 */
padding: 0 14px;
gap: 10px;
```

### Drawer
```css
width: 0;  /* closed */
width: 280px;  /* open */
transition: width 0.2s ease;
background: var(--bg1);
border-left: 1px solid var(--br);
```

### Play button (round)
```css
background: var(--acc);  /* #6c8cff */
color: var(--bg0);  /* #08090d */
border-radius: 50%;
width: 28px;
height: 28px;
```

### Progress bar
```css
height: 3px;
background: var(--br);
border-radius: 2px;
/* Fill: */
background: var(--acc);
```

### Nav rail
```css
width: 36px;
background: var(--bg0);
border-right: 1px solid var(--br);
```

### Drag insertion indicator
```css
border-top: 2px solid var(--acc);
```

### Dragging item
```css
opacity: 0.3;
```

---

## 12. Keyboard Shortcuts (additions)

Add these to the existing keyboard handler:

| Key | Action |
|-----|--------|
| `[` | Toggle nav sidebar collapsed/expanded |
| `Space` | Play/pause (when not in input) |
| `]` | Toggle right drawer |

Update the keyboard shortcut footer in the nav to show the new shortcuts.

---

## 13. Notes on Audio Playback

The app uses kokoro-edge at `localhost:7777` for TTS generation. For playback, use a standard HTML5 `<audio>` element:

- On track load: set `audio.src` to the rendition URL from the document's `renditions.audio.url`
- The `<audio>` element should be a singleton in the React tree (not re-mounted on track change)
- Listen for `timeupdate` to update progress bar and position state
- Listen for `ended` to auto-advance to next track
- Listen for `loadedmetadata` to get actual duration (may differ from stored duration)

For tracks using `useSummary: true`, load from `renditions.audio_summary.url` instead of `renditions.audio.url`.
