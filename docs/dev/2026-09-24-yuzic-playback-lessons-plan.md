# Playback lessons from Yuzic — Implementation Plan

> Execute with dev-flow: one task at a time, review after each task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** implement spec R1–R7 (resume, history/previous, content-kind table,
unreachable detection, media-session position, constants doc, loudness).
**Architecture:** pure helpers (`contentKind.ts`, `bookmarks.ts`,
`loudness.ts`) + store changes (history, persisted current, strip helper) +
Player wiring. Backend change is one optional model field read in the adapter.
**Tech stack:** Svelte 5 runes, vitest + @testing-library/svelte (jsdom),
FastAPI/Pydantic, pytest.
**Spec:** `docs/dev/2026-09-24-yuzic-playback-lessons-spec.md`
**Baseline (2026-09-24, before any edit, `./scripts/check.sh` exit 0):**
ruff clean, mypy clean, pytest **204 passed, 5 deselected**, svelte-check
clean, vitest **187 passed (21 files)**, vite build ok. No failing tests.

## Global Constraints

- Signed URLs (`audioUrl`, `hlsUrl`, `liveStreamUrl`) and `_formats` are never
  written to localStorage. All stripping goes through `stripSignedUrls()`.
- localStorage keys: `hum.current`, `hum.history`, `hum.bookmarks`,
  `hum.normalize` (new); existing keys unchanged.
- Constants: `BOOKMARK_MIN_DURATION_S = 600`, `BOOKMARK_END_MARGIN_S = 30`,
  `BOOKMARK_MAX_ENTRIES = 200`, `POSITION_SAVE_INTERVAL_MS = 5000`,
  `HISTORY_MAX = 50`, `PREVIOUS_RESTART_THRESHOLD_S = 3`,
  `SEEK_STEP_S = 10`.
- Toast copy: `"Can't reach Hum server."` (sticky, action label `Retry`).
- Button aria-label: `"Previous track"` (replaces `"Restart track"`).
- `ApiError.status === 0` means "Hum server unreachable"; reserved.
- Every localStorage access wrapped in try/catch.
- `app/models.py` ⇄ `frontend/src/lib/types.ts` updated together.
- Every commit passes `./scripts/check.sh fast`; final state passes
  `./scripts/check.sh`.

## File map

| File | Responsibility | Tasks |
|---|---|---|
| `frontend/src/lib/contentKind.ts` (new) | kind → behaviour table | 1 |
| `frontend/src/lib/api.ts` | status-0 errors, `health()`, `isUnreachable()` | 2 |
| `frontend/src/lib/bookmarks.ts` (new) | per-video resume positions | 3 |
| `frontend/src/lib/store.svelte.ts` | strip helper, persisted current/history, `previous()`, `startPositionFor()`, `notifyUnreachable()`, normalize setting | 4, 6 |
| `frontend/src/components/Player.svelte` | start seek, position saves, autoplay gating, prev, mediaSession, unreachable path, volume gain | 5, 6 |
| `frontend/src/components/NowPlaying.svelte` | prev button, kind accessors | 5 |
| `frontend/src/lib/loudness.ts` (new) | dB → gain | 6 |
| `frontend/src/pages/Settings.svelte` | normalize toggle | 6 |
| `app/models.py`, `app/adapters/youtube.py`, `frontend/src/lib/types.ts` | `loudness_db` | 6 |
| `docs/ARCHITECTURE.md`, `CLAUDE.md` | constants table, coupling updates | 7 |

---

### Task 1: content-kind table (R3)

**Files:** Create `frontend/src/lib/contentKind.ts`; Test
`frontend/tests/unit/contentKind.test.ts`; Modify `Player.svelte`,
`NowPlaying.svelte` behavioural `isLive` reads.

**Produces:** `ContentKind`, `kindOf`, `hasDuration`, `isSeekable`,
`isBookmarkable`, `isAirplayRoutable`, `usesHls` — each `(t: Track | null | undefined) => boolean`
(false for null).

- [ ] Step 1: failing test

```ts
import { describe, it, expect } from 'vitest';
import { kindOf, hasDuration, isSeekable, isBookmarkable, isAirplayRoutable, usesHls } from '../../src/lib/contentKind';
const vod = { isLive: false } as any, live = { isLive: true } as any, legacy = {} as any;
describe('contentKind', () => {
  it('classifies', () => {
    expect(kindOf(vod)).toBe('vod'); expect(kindOf(live)).toBe('live');
    expect(kindOf(legacy)).toBe('vod'); expect(kindOf(null)).toBeNull();
  });
  it('vod row', () => {
    for (const f of [hasDuration, isSeekable, isBookmarkable, isAirplayRoutable]) expect(f(vod)).toBe(true);
    expect(usesHls(vod)).toBe(false);
  });
  it('live row', () => {
    for (const f of [hasDuration, isSeekable, isBookmarkable, isAirplayRoutable]) expect(f(live)).toBe(false);
    expect(usesHls(live)).toBe(true);
  });
  it('null is false everywhere', () => {
    for (const f of [hasDuration, isSeekable, isBookmarkable, isAirplayRoutable, usesHls]) expect(f(null)).toBe(false);
  });
});
```

- [ ] Step 2: run `npm --prefix frontend test -- contentKind` → FAIL (module missing).
- [ ] Step 3: implement

```ts
import type { Track } from './types';

// One row per kind of thing the player can hold (Yuzic's contentKind idea).
// Call sites ask a behaviour question, never `t.isLive` directly, so a new
// kind is one row here rather than a branch at every site.
export type ContentKind = 'vod' | 'live';

type Behaviour = {
  hasDuration: boolean; isSeekable: boolean; isBookmarkable: boolean;
  isAirplayRoutable: boolean; usesHls: boolean;
};

const TABLE: Record<ContentKind, Behaviour> = {
  vod:  { hasDuration: true,  isSeekable: true,  isBookmarkable: true,  isAirplayRoutable: true,  usesHls: false },
  live: { hasDuration: false, isSeekable: false, isBookmarkable: false, isAirplayRoutable: false, usesHls: true },
};

type Kinded = Pick<Track, 'isLive'> | null | undefined;

export function kindOf(t: Kinded): ContentKind | null {
  if (!t) return null;
  return t.isLive ? 'live' : 'vod';
}

function ask(k: keyof Behaviour) {
  return (t: Kinded): boolean => { const kind = kindOf(t); return kind ? TABLE[kind][k] : false; };
}

export const hasDuration = ask('hasDuration');
export const isSeekable = ask('isSeekable');
export const isBookmarkable = ask('isBookmarkable');
export const isAirplayRoutable = ask('isAirplayRoutable');
export const usesHls = ask('usesHls');
```

- [ ] Step 4: replace behavioural reads —
  Player: L22 `t.isLive` → `usesHls(t)`; L162 `!…isLive` → `isAirplayRoutable(store.player.current)`;
  L199/L297/L317/L357 → `usesHls(t)`; L488 `{#if !…isLive}` → `{#if isSeekable(store.player.current)}`.
  NowPlaying: L165 quality row → `{#if !usesHls(t)}`; L190 scrubber → `{#if isSeekable(t)}`;
  L220 prev → `{#if isSeekable(t)}`. Leave L149 (LIVE pill) and Player L532 (pill) as data reads.
- [ ] Step 5: `./scripts/check.sh fast` → vitest 187+4 pass; commit `refactor(frontend): content-kind behaviour table`.

### Task 2: unreachable detection in the API client (R4.1)

**Files:** Modify `frontend/src/lib/api.ts`; Test `frontend/tests/unit/api.test.ts`.
**Produces:** `ApiError(0, …)` on fetch rejection; `api.health(): Promise<void>`;
`isUnreachable(e: unknown): boolean`.

- [ ] Step 1: failing tests (append to `api.test.ts`)

```ts
it('fetch rejection becomes ApiError status 0', async () => {
  store.setToken('T');
  (globalThis.fetch as any).mockRejectedValue(new TypeError('Failed to fetch'));
  await expect(api.video('x')).rejects.toMatchObject({ status: 0 });
});
it('health resolves on 200 and does not send bearer', async () => {
  (globalThis.fetch as any).mockResolvedValue({ ok: true, status: 200 });
  await expect(api.health()).resolves.toBeUndefined();
  expect((globalThis.fetch as any).mock.calls[0][0]).toBe('/health');
});
it('health rejection is status 0; isUnreachable detects it', async () => {
  (globalThis.fetch as any).mockRejectedValue(new TypeError('x'));
  const e = await api.health().catch((x) => x);
  expect(isUnreachable(e)).toBe(true);
  expect(isUnreachable(new ApiError(502, 'x'))).toBe(false);
});
```
(import `isUnreachable` alongside `api, ApiError`.)

- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement in `api.ts`

```ts
// Status 0 is reserved: the request never reached Hum (server down, Wi-Fi
// gone, laptop asleep). Distinct from a 5xx, which means Hum answered but
// YouTube failed. Recovery UI keys off the difference (Yuzic's "offline vs
// server unreachable" split).
export function isUnreachable(e: unknown): boolean {
  return e instanceof ApiError && e.status === 0;
}
```
In `request()`: `let resp: Response; try { resp = await fetch(path, { ...init, headers }); } catch { throw new ApiError(0, 'hum server unreachable'); }`.
In `api`: 
```ts
  // Public liveness probe (app/main.py /health, no bearer). Used by the
  // player to tell "Hum is down" from "this stream failed".
  health: async (): Promise<void> => {
    let r: Response;
    try { r = await fetch('/health'); } catch { throw new ApiError(0, 'hum server unreachable'); }
    if (!r.ok) throw new ApiError(r.status, 'unhealthy');
  },
```
- [ ] Step 4: `check.sh fast` green; commit `feat(api): distinguish unreachable Hum server (status 0)`.

### Task 3: bookmarks module (R1.3)

**Files:** Create `frontend/src/lib/bookmarks.ts`; Test `frontend/tests/unit/bookmarks.test.ts`.
**Produces:** `getBookmark(id): number | null`, `saveBookmark(id, pos, dur, now?)`,
`clearBookmark(id)`, constants `BOOKMARK_MIN_DURATION_S`, `BOOKMARK_END_MARGIN_S`, `BOOKMARK_MAX_ENTRIES`.

- [ ] Step 1: failing tests

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import { getBookmark, saveBookmark, clearBookmark, BOOKMARK_MAX_ENTRIES } from '../../src/lib/bookmarks';
beforeEach(() => localStorage.clear());
describe('bookmarks', () => {
  it('ignores short tracks', () => { saveBookmark('a', 100, 599); expect(getBookmark('a')).toBeNull(); });
  it('saves long tracks', () => { saveBookmark('a', 100, 600); expect(getBookmark('a')).toBe(100); });
  it('clears near the end', () => {
    saveBookmark('a', 100, 1000); saveBookmark('a', 971, 1000); expect(getBookmark('a')).toBeNull();
  });
  it('does not keep a position under 5 s', () => { saveBookmark('a', 3, 1000); expect(getBookmark('a')).toBeNull(); });
  it('clearBookmark removes', () => { saveBookmark('a', 100, 1000); clearBookmark('a'); expect(getBookmark('a')).toBeNull(); });
  it('evicts oldest beyond cap', () => {
    for (let i = 0; i <= BOOKMARK_MAX_ENTRIES; i++) saveBookmark('v' + i, 100, 1000, i);
    expect(getBookmark('v0')).toBeNull();
    expect(getBookmark('v' + BOOKMARK_MAX_ENTRIES)).toBe(100);
  });
  it('survives corrupt storage', () => { localStorage.setItem('hum.bookmarks', '{bad'); expect(getBookmark('a')).toBeNull(); });
});
```
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement

```ts
// Per-video resume positions for long content (Yuzic's playback bookmarks).
// Only videos >= BOOKMARK_MIN_DURATION_S are worth resuming; a 3-minute song
// should always start at 0. Values are plain seconds — never URLs.
const KEY = 'hum.bookmarks';
export const BOOKMARK_MIN_DURATION_S = 600;
export const BOOKMARK_END_MARGIN_S = 30;
export const BOOKMARK_MAX_ENTRIES = 200;
const MIN_POSITION_S = 5;

type Entry = { pos: number; at: number };

function load(): Record<string, Entry> {
  try {
    const raw = localStorage.getItem(KEY);
    const v = raw ? JSON.parse(raw) : {};
    return v && typeof v === 'object' ? v : {};
  } catch { return {}; }
}
function store(all: Record<string, Entry>): void {
  try { localStorage.setItem(KEY, JSON.stringify(all)); } catch { /* best-effort */ }
}

export function getBookmark(id: string): number | null {
  const e = load()[id];
  return e && Number.isFinite(e.pos) ? e.pos : null;
}

export function clearBookmark(id: string): void {
  const all = load();
  if (!(id in all)) return;
  delete all[id];
  store(all);
}

export function saveBookmark(id: string, pos: number, dur: number, now: number = Date.now()): void {
  if (!Number.isFinite(dur) || dur < BOOKMARK_MIN_DURATION_S) return;
  if (pos < MIN_POSITION_S || pos >= dur - BOOKMARK_END_MARGIN_S) { clearBookmark(id); return; }
  const all = load();
  all[id] = { pos, at: now };
  const ids = Object.keys(all);
  if (ids.length > BOOKMARK_MAX_ENTRIES) {
    ids.sort((a, b) => all[a].at - all[b].at);
    for (const old of ids.slice(0, ids.length - BOOKMARK_MAX_ENTRIES)) delete all[old];
  }
  store(all);
}
```
- [ ] Step 4: `check.sh fast`; commit `feat(frontend): per-video resume bookmarks`.

### Task 4: store — strip helper, persisted current + history, previous (R1.1, R1.2, R2.1–R2.3, R2.5)

**Files:** Modify `frontend/src/lib/store.svelte.ts`; Test `frontend/tests/unit/store.test.ts`.
**Consumes:** `getBookmark` (Task 3), `isSeekable`, `isBookmarkable` (Task 1), `playerControls`.
**Produces:** `stripSignedUrls(t)`, `store.history`, `store.previous()`,
`store.startPositionFor(t): number`, `store.setPosition(s)`, `PlayerControls.seekTo?(s)`,
`HISTORY_MAX`, `PREVIOUS_RESTART_THRESHOLD_S`.

Design notes:
- `player.positionSeconds` becomes "last known playback position", written by
  Player every `POSITION_SAVE_INTERVAL_MS` (Task 5) and persisted with current
  as `hum.current = { track, pos }`.
- Restore: `current = stripSignedUrls(saved.track)`, `isPlaying = false`,
  `positionSeconds = saved.pos`, and private `#restoredId = track.videoId`.
- `startPositionFor(t)`: if `t.videoId === #restoredId` → consume flag, return
  `positionSeconds`; else if `isBookmarkable(t) && durationSeconds >= 600` →
  `getBookmark(id) ?? 0`; else 0. (bookmarks.getBookmark already returns null for
  unsaved; the duration check mirrors R1.4.)
- `#pushHistory(t)`: append `t`, trim to last `HISTORY_MAX`.
- `playNow(t)`: if current && current.videoId !== t.videoId → push.
- `next()`: repeat-one branch and repeat-all-empty-queue branch unchanged (no push);
  stop branch (queue empty, repeat off) pushes current; pick branch pushes current.
- `previous()`: `pos = playerControls.current?.getPosition?.() ?? 0`. If
  `!current` return. If `pos > 3 || history.length === 0` → if `isSeekable(current)`
  call `playerControls.current?.seekTo?.(0)`; return. Else pop history → current,
  old current unshifted to queue front, `isPlaying = true`, `positionSeconds = 0`.
- Flush effect also touches `this.player.current`, `this.player.positionSeconds`,
  `this.history.length`; flush writes `hum.current` (or removes it when null) and
  `hum.history`, all via `stripSignedUrls`.

- [ ] Step 1: failing tests (append; use existing `t()` + `freshStore()`; add
  `mod.store.history = []` to `freshStore`)

```ts
describe('history + previous', () => {
  it('next pushes outgoing current to history', async () => {
    const s = await freshStore(); s.playNow(t('a')); s.enqueue(t('b')); s.next();
    expect(s.history.map((x) => x.videoId)).toEqual(['a']);
  });
  it('repeat one does not push', async () => {
    const s = await freshStore(); s.playNow(t('a')); s.player.repeat = 'one'; s.next();
    expect(s.history).toEqual([]);
  });
  it('playNow of a different track pushes; same track does not', async () => {
    const s = await freshStore(); s.playNow(t('a')); s.playNow(t('a')); s.playNow(t('b'));
    expect(s.history.map((x) => x.videoId)).toEqual(['a']);
  });
  it('history is capped', async () => {
    const s = await freshStore(); s.playNow(t('x0'));
    for (let i = 1; i <= 60; i++) s.playNow(t('x' + i));
    expect(s.history.length).toBe(50); expect(s.history[0].videoId).toBe('x10');
  });
  it('previous within threshold goes back and requeues current at front', async () => {
    const mod = await import('../../src/lib/store.svelte'); const s = await freshStore();
    mod.playerControls.current = { getPosition: () => 1, seekTo: vi.fn() } as any;
    s.playNow(t('a')); s.enqueue(t('c')); s.playNow(t('b')); s.previous();
    expect(s.player.current?.videoId).toBe('a');
    expect(s.queue.map((x) => x.videoId)).toEqual(['b', 'c']);
    expect(s.history).toEqual([]);
    mod.playerControls.current = null;
  });
  it('previous past threshold restarts via seekTo(0)', async () => {
    const mod = await import('../../src/lib/store.svelte'); const s = await freshStore();
    const seekTo = vi.fn(); mod.playerControls.current = { getPosition: () => 10, seekTo } as any;
    s.playNow(t('a')); s.playNow(t('b')); s.previous();
    expect(seekTo).toHaveBeenCalledWith(0); expect(s.player.current?.videoId).toBe('b');
    mod.playerControls.current = null;
  });
  it('previous with empty history restarts', async () => {
    const mod = await import('../../src/lib/store.svelte'); const s = await freshStore();
    const seekTo = vi.fn(); mod.playerControls.current = { getPosition: () => 0, seekTo } as any;
    s.playNow(t('a')); s.previous(); expect(seekTo).toHaveBeenCalledWith(0);
    mod.playerControls.current = null;
  });
});

describe('persisted current + history', () => {
  it('stripSignedUrls removes every URL field and _formats', async () => {
    const { stripSignedUrls } = await import('../../src/lib/store.svelte');
    const out = stripSignedUrls({ ...t('a'), hlsUrl: '/h', liveStreamUrl: '/l', _formats: [] as any });
    expect(out.audioUrl).toBe(''); expect(out.hlsUrl).toBeUndefined();
    expect(out.liveStreamUrl).toBeUndefined(); expect('_formats' in out).toBe(false);
  });
  it('flush writes current, position and history without URLs', async () => {
    const s = await freshStore(); s.playNow(t('a')); s.playNow(t('b')); s.setPosition(42);
    await new Promise((r) => setTimeout(r, 250));
    const cur = JSON.parse(localStorage.getItem('hum.current')!);
    expect(cur.track.videoId).toBe('b'); expect(cur.track.audioUrl).toBe(''); expect(cur.pos).toBe(42);
    const hist = JSON.parse(localStorage.getItem('hum.history')!);
    expect(hist[0].videoId).toBe('a'); expect(hist[0].audioUrl).toBe('');
  });
  it('rehydrates current paused at saved position; startPositionFor consumes it once', async () => {
    localStorage.setItem('hum.current', JSON.stringify({ track: { ...t('a'), audioUrl: '/stale' }, pos: 77 }));
    localStorage.setItem('hum.history', JSON.stringify([{ ...t('z'), audioUrl: '/stale' }]));
    vi.resetModules();
    const { store: s } = await import('../../src/lib/store.svelte');
    expect(s.player.current?.videoId).toBe('a'); expect(s.player.current?.audioUrl).toBe('');
    expect(s.player.isPlaying).toBe(false); expect(s.history[0].audioUrl).toBe('');
    expect(s.startPositionFor(s.player.current!)).toBe(77);
    expect(s.startPositionFor(s.player.current!)).toBe(0);
  });
  it('startPositionFor uses bookmark only for long vod', async () => {
    const s = await freshStore();
    localStorage.setItem('hum.bookmarks', JSON.stringify({ L: { pos: 300, at: 1 }, S: { pos: 50, at: 1 } }));
    expect(s.startPositionFor({ ...t('L'), durationSeconds: 1200 })).toBe(300);
    expect(s.startPositionFor({ ...t('S'), durationSeconds: 200 })).toBe(0);
    expect(s.startPositionFor({ ...t('L'), durationSeconds: 1200, isLive: true })).toBe(0);
  });
});
```
- [ ] Step 2: run `npm --prefix frontend test -- store` → new tests FAIL, old pass.
- [ ] Step 3: implement per design notes. Strip helper:

```ts
// The ONE place signed URLs are stripped before persistence and after
// rehydrate. audioUrl/hlsUrl/liveStreamUrl all expire; _formats carries more
// of them. A new signed-URL field on Track is stripped here and nowhere else.
export function stripSignedUrls(t: Track): Track {
  const { _formats, ...rest } = t;
  void _formats;
  return { ...rest, audioUrl: '', hlsUrl: undefined, liveStreamUrl: undefined };
}
```
Queue rehydrate and `#flush` queue map both call it. Add `seekTo?: (s: number) => void`
to `PlayerControls`; `setPosition(s: number) { this.player.positionSeconds = s; }`.
- [ ] Step 4: `check.sh fast` → all store tests (old + new) pass; commit
  `feat(store): persist current track + history, add previous()`.

### Task 5: Player/NowPlaying wiring — start position, saves, prev, media session, unreachable (R1.2, R1.4, R1.5, R2.4, R4.2, R4.3, R5)

**Files:** Modify `Player.svelte`, `NowPlaying.svelte`, `store.svelte.ts`
(`notifyUnreachable`); Test `frontend/tests/components/Player.test.ts`,
`frontend/tests/components/NowPlaying.test.ts`.
**Consumes:** Tasks 1–4.

Changes:
1. `playerControls.current.seekTo = (s) => { if (el) el.currentTime = Math.max(0, s); }`.
2. `<audio autoplay={store.player.isPlaying} onplay={() => store.player.isPlaying = true} onpause={onPause} ontimeupdate={onTimeUpdate} onloadedmetadata={updatePositionState} onseeked={updatePositionState} onratechange={updatePositionState}>`.
3. Start seek: in the `currentVideoId` effect, after metadata setup:
   `const start = store.startPositionFor(t); if (start > 0) playerControls.current?.restoreAt?.(start);`
4. Saves: `onTimeUpdate` → if `Date.now() - lastSave >= POSITION_SAVE_INTERVAL_MS` →
   `savePos()`. `savePos()` → `store.setPosition(el.currentTime)`; if `isBookmarkable(t)`
   → `saveBookmark(t.videoId, el.currentTime, el.duration || t.durationSeconds)`.
   `onPause` → `store.player.isPlaying = false; savePos()`. `pagehide` listener →
   `savePos()`. `advance()` (onended) → `clearBookmark(id)` before `store.next()`.
5. Prev: Player button & NowPlaying button → `store.previous()`, aria-label
   `"Previous track"`; `mediaSession previoustrack` → `store.previous()`.
   NowPlaying `restartTrack` removed.
6. Media Session: `updatePositionState()` — if `'mediaSession' in navigator &&
   navigator.mediaSession.setPositionState`: for `hasDuration(t)` and finite
   `el.duration > 0` → `setPositionState({ duration: el.duration, position:
   Math.min(el.currentTime, el.duration), playbackRate: el.playbackRate || 1 })`;
   else `setPositionState()`; try/catch. In the metadata effect register
   `seekto` (`details.seekTime`), `seekbackward`/`seekforward`
   (`details.seekOffset ?? SEEK_STEP_S`) when `isSeekable(t)`, else set those three to `null`.
7. Unreachable: `store.notifyUnreachable(retry: () => void)` → sticky toast
   `"Can't reach Hum server."` with `Retry`. In `handleError`, after the live and
   empty-src guards: `if (await api.health().then(() => false, isUnreachable)) { store.notifyUnreachable(() => { if (el) { el.load(); safePlay(el); } }); return; }`
   (before codec + recovery slots). VOD/live rehydrate `.catch((e) => isUnreachable(e) ? store.notifyUnreachable(...) : <existing toast>)`
   with retry re-assigning `store.player.current = { ...t }`. `#fetchTrack` catch:
   `isUnreachable(e)` → `notifyUnreachable(() => {})`-style toast without retry
   (the user re-clicks); implement as `this.notify("Can't reach Hum server.", 'error')`.

- [ ] Step 1: failing tests (Player.test.ts; add `vi.spyOn(api, 'health').mockResolvedValue()` in the top-level `beforeEach`, import `api`)

```ts
describe('Player — resume, prev, media session, unreachable', () => {
  it('does not autoplay a restored (isPlaying=false) track', async () => {
    store.player.current = sampleTrack('r', '/proxy/audio/r?x'); store.player.isPlaying = false;
    const { container } = render(Player); await tick();
    expect((container.querySelector('audio') as HTMLAudioElement).autoplay).toBe(false);
  });
  it('previous button calls store.previous', async () => {
    const spy = vi.spyOn(store, 'previous');
    store.playNow(sampleTrack('p', '/proxy/audio/p?x'));
    const { getByLabelText } = render(Player); await tick();
    getByLabelText('Previous track').click(); expect(spy).toHaveBeenCalled(); spy.mockRestore();
  });
  it('registers seek handlers and position state for vod', async () => {
    const handlers: Record<string, any> = {}; const setPositionState = vi.fn();
    (navigator as any).mediaSession = { metadata: null, setActionHandler: (k: string, f: any) => { handlers[k] = f; }, setPositionState };
    (globalThis as any).MediaMetadata = class { constructor(public o: any) {} };
    store.playNow(sampleTrack('m', '/proxy/audio/m?x'));
    const { container } = render(Player); await tick();
    expect(typeof handlers.seekto).toBe('function');
    const audio = container.querySelector('audio') as HTMLAudioElement;
    Object.defineProperty(audio, 'duration', { value: 200, configurable: true });
    audio.dispatchEvent(new Event('loadedmetadata'));
    expect(setPositionState).toHaveBeenCalledWith(expect.objectContaining({ duration: 200 }));
    delete (navigator as any).mediaSession;
  });
  it('unreachable server: shows Hum toast and keeps recovery slot', async () => {
    vi.spyOn(api, 'health').mockRejectedValue(new ApiError(0, 'x'));
    const video = vi.spyOn(api, 'video');
    store.playNow(sampleTrack('u', '/proxy/audio/u?x'));
    const { container } = render(Player); await tick();
    container.querySelector('audio')!.dispatchEvent(new Event('error'));
    await new Promise((r) => setTimeout(r, 0)); await tick();
    expect(store.toast?.message).toBe("Can't reach Hum server.");
    expect(video).not.toHaveBeenCalled();
  });
});
```
NowPlaying.test.ts: `'prev button is labelled Previous track and calls store.previous'` (same shape).
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement changes 1–7.
- [ ] Step 4: `check.sh fast`; existing Player codec tests still pass (health mocked resolved); commit
  `feat(player): resume position, previous, media-session seek, unreachable toast`.

### Task 6: loudness attenuation (R7)

> **Dropped (2026-09-24):** not shipped. 0.2.0 replaced pytubefix with yt-dlp, which does not expose `loudnessDb`. Kept here as a record.


**Files:** Modify `app/models.py`, `app/adapters/youtube.py`,
`frontend/src/lib/types.ts`, `store.svelte.ts` (`#buildTrack`, `settings.normalizeLoudness`,
`setNormalizeLoudness`, key `hum.normalize`), `Player.svelte`, `Settings.svelte`;
Create `frontend/src/lib/loudness.ts`; Tests `tests/unit/test_youtube_adapter.py`,
`tests/integration/test_youtube_live.py`, `frontend/tests/unit/loudness.test.ts`,
`frontend/tests/components/Player.test.ts`.

- [ ] Step 1: failing pytest

```python
import pytest

@pytest.mark.parametrize(
    ("vid_info", "expected"),
    [
        ({"playerConfig": {"audioConfig": {"loudnessDb": 3.5}}}, 3.5),
        ({"playerConfig": {"audioConfig": {"loudnessDb": -2}}}, -2.0),
        ({"playerConfig": {"audioConfig": {}}}, None),
        ({"playerConfig": None}, None),
        ({}, None),
        ({"playerConfig": {"audioConfig": {"loudnessDb": "loud"}}}, None),
        ({"playerConfig": {"audioConfig": {"loudnessDb": True}}}, None),
        ({"playerConfig": {"audioConfig": {"loudnessDb": float("nan")}}}, None),
    ],
)
def test_loudness_db_parsing(vid_info: dict[str, object], expected: float | None) -> None:
    from app.adapters.youtube import _loudness_db

    class Y:
        pass

    y = Y()
    y.vid_info = vid_info  # type: ignore[attr-defined]
    assert _loudness_db(y) == expected
```
Plus: in `test_normalise_video_falls_through_to_vod_when_is_live_false`'s sibling,
a new test with `vid_info = {"videoDetails": {"isLive": False}, "playerConfig": {"audioConfig": {"loudnessDb": 1.5}}}`
asserting `details.loudness_db == 1.5`. Integration (opt-in):
```python
async def test_video_loudness_live() -> None:
    v = await youtube.video("dQw4w9WgXcQ")
    assert isinstance(v.loudness_db, float), "YouTube no longer exposes playerConfig.audioConfig.loudnessDb"
```
- [ ] Step 2: `uv run pytest tests/unit/test_youtube_adapter.py -q` → FAIL.
- [ ] Step 3: backend

```python
def _loudness_db(yt: Any) -> float | None:
    """YouTube's per-video loudness offset (dB vs its playback reference).

    Read from vid_info.playerConfig.audioConfig.loudnessDb. Positive means
    louder than reference. Absent/garbage → None; the frontend then leaves
    volume alone. bool is rejected explicitly (it is an int subclass).
    """
    try:
        cfg = (yt.vid_info.get("playerConfig") or {}).get("audioConfig") or {}
        value = cfg.get("loudnessDb")
    except Exception:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None
```
`VideoDetails.loudness_db: float | None = None`; `_normalise_vod_video` passes
`loudness_db=_loudness_db(yt)`. `types.ts`: `loudness_db?: number | null` on
`VideoDetails`, `loudnessDb?: number` on `Track`; `#buildTrack` VOD branch sets
`loudnessDb: d.loudness_db ?? undefined`.
- [ ] Step 4: frontend failing tests

```ts
import { loudnessGain } from '../../src/lib/loudness';
it('attenuates loud, never boosts', () => {
  expect(loudnessGain(6)).toBeCloseTo(0.501, 3);
  expect(loudnessGain(0)).toBe(1); expect(loudnessGain(-5)).toBe(1);
  expect(loudnessGain(undefined)).toBe(1); expect(loudnessGain(null)).toBe(1);
});
```
Player: `'applies loudness gain to element volume when normalize is on'` — track with
`loudnessDb: 6`, `store.settings.normalizeLoudness = true` → `audio.volume ≈ 0.501`;
set `false` → `1`.
- [ ] Step 5: implement

```ts
// YouTube reports how much louder than its reference a track is mastered.
// Attenuate-only (like YouTube's own player): never boost, so no clipping.
export function loudnessGain(db: number | null | undefined): number {
  if (db == null || !Number.isFinite(db) || db <= 0) return 1;
  return Math.pow(10, -db / 20);
}
```
Player: `let userVolume = $state(1)`; `setVolume` sets `userVolume`; effect:
`if (el) el.volume = userVolume * (store.settings.normalizeLoudness ? loudnessGain(store.player.current?.loudnessDb) : 1);`.
Settings: toggle row "Normalize loudness" / "Turn down tracks mastered louder than
average. Uses YouTube's loudness data; has no effect on iPhone and iPad." Store:
`normalizeLoudness: loadString(KEY_NORMALIZE) === 'false' ? false : true`, persisted in `#flush`.
- [ ] Step 6: `check.sh fast`; commit `feat: attenuate-only loudness normalization`.

### Task 7: docs (R6 + couplings)

**Files:** `docs/ARCHITECTURE.md`, `CLAUDE.md`, `docs/BACKLOG.md`.
- [ ] Step 1: read actual values: `grep -n` for `_CACHE_MAX_TTL`, `_MASTER_CACHE_TTL_S`,
  `_TARGET_SEGMENT_SECONDS`, `PERSIST_DEBOUNCE_MS`, hls.js config in Player, and the
  Global-Constraints constants; write the table "Tuning constants (reasoned, not
  measured)" with value · location · what it decides.
- [ ] Step 2: ARCHITECTURE: short "Playback state" subsection (current/history/bookmarks
  persistence, `stripSignedUrls`, content-kind table, status-0 unreachable).
- [ ] Step 3: CLAUDE.md couplings: replace the "strip it in `#flush()` **and** the
  queue-rehydrate map" bullet with "strip it in `stripSignedUrls()` (store.svelte.ts)";
  add `contentKind.ts` note under landmines ("ask behaviour, don't read `isLive`").
  BACKLOG P3: "Verify `loudness_db` with `pytest -m integration` (unverified from CI sandbox)".
- [ ] Step 4: `./scripts/check.sh` full → green; commit `docs: playback state, tuning constants`.

---

## Self-review

- Spec coverage: R1.1→T4; R1.2→T4+T5; R1.3→T3+T5; R1.4→T4 (`startPositionFor`)+T5;
  R1.5→T1 table + T4; R2.1–2.3,2.5→T4; R2.4→T5 (App has no restart binding — nothing to
  wire, verified `App.svelte:82-106`); R3→T1; R4.1→T2; R4.2–4.4→T5; R5→T5; R6→T7; R7→T6.
- Placeholders: none.
- Names consistent: `stripSignedUrls`, `startPositionFor`, `setPosition`, `seekTo`,
  `notifyUnreachable`, `isUnreachable`, `loudnessGain`, `loudness_db`/`loudnessDb`,
  `normalizeLoudness`.
