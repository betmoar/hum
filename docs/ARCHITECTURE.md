# Hum Architecture

Lean self-hosted YouTube proxy + lightweight Svelte 5 frontend. Single process, single binary deployment.

> Maintainer entry points: [CLAUDE.md](../CLAUDE.md) (mental model, landmines, couplings),
> [PLAYBOOKS.md](PLAYBOOKS.md) (step-by-step procedures), [BACKLOG.md](BACKLOG.md)
> (known debt + residual risks). The invariants below are enforced by
> `tests/unit/test_invariants.py`. Pre-push gate: `./scripts/check.sh`.

## Overview

```
┌─────────────┐     bearer-auth     ┌─────────────┐
│  Frontend   │ ─────────────────▶  │   FastAPI   │
│ (Svelte 5)  │ ◀─── signed URL ─── │   Backend   │
└─────────────┘                     └─────┬───────┘
       │                                  │
       │ <audio src="signed URL">         │ yt_dlp.YoutubeDL(...)
       │                                  ▼
       │                            ┌─────────────┐
       └─── direct HTTPS (range) ──▶│ YouTube CDN │
                                    └─────────────┘
```

In production both layers ship as one Docker image:
- Stage 1: `node:20-alpine` builds `frontend/dist/`
- Stage 2: `python:3.11-slim` installs the backend and copies `dist/` in
- `uvicorn app.main:app` serves both on port 8000

## Backend

Ports-and-adapters layout. Three load-bearing invariants:

1. `yt_dlp` is imported in exactly one file: [app/adapters/youtube.py](../app/adapters/youtube.py)
2. Upstream HTTP goes through exactly one `httpx.AsyncClient` in [app/adapters/upstream_http.py](../app/adapters/upstream_http.py)
3. Stream URLs handed to clients are **always** Blake3-HMAC-signed; raw YouTube CDN URLs never leave the proxy

### Module layout

```
app/
├── main.py               FastAPI app, lifespan, exception handler, CORS, mount
├── config.py             Pydantic settings (env vars)
├── auth.py               Bearer dependency + Blake3 URL signing
├── models.py             Pydantic response shapes
├── static.py             Mount frontend/dist/ at / with SPA fallback
├── adapters/
│   ├── youtube.py        Only file that imports yt_dlp
│   └── upstream_http.py  Shared httpx.AsyncClient + YouTube host allowlist
├── api/                  GET routes: search, video, channel, playlist
└── proxy/                GET routes: audio, video, thumbnail + shared helpers
```

### Routes

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/search?q&limit` | bearer | Search (videos + channels + playlists) |
| GET | `/api/video/{id}` | bearer | Metadata + signed proxy URLs |
| GET | `/api/channel/{id}` | bearer | Channel info |
| GET | `/api/playlist/{id}` | bearer | Playlist with items |
| GET | `/proxy/audio/{id}?itag&exp&sig` | signed URL | Audio stream (range-aware) |
| GET | `/proxy/stream/{id}?itag&exp&sig` | signed URL | Video stream (range-aware) |
| GET | `/proxy/thumbnail/{id}?itag=0&exp&sig` | signed URL | Thumbnail |
| GET | `/health` | none | Health check |
| GET | `/{path}` | none | SPA fallback → `index.html` |

### Auth model

**API auth** — single shared bearer token from `API_BEARER_TOKEN`. Compared with `secrets.compare_digest` to prevent timing attacks. 401 on miss/mismatch.

**Stream URL signing** — Blake3-keyed HMAC of `{path}|{itag}|{exp}`, truncated to 32 hex chars. URLs minted by `/api/video/{id}` with a 6h TTL (`STREAM_URL_TTL_SECONDS`). Each proxy endpoint independently verifies before opening the upstream stream.

Why two layers: the bearer protects the JSON API. Signed URLs let us hand stream URLs to `<audio>` elements (which can't reliably send custom headers) without leaking access. Signed URLs leak less because they're scoped to one `(video_id, itag)` and expire.

### Upstream

The adapter's `resolve_upstream_url(video_id, itag)` returns the YouTube CDN URL. Backed by a process-level in-memory cache `(video_id, itag) → (url, expiry_epoch)` with TTL = `min(YouTube's expire param, 1 hour)`. Cache misses fall through to a fresh yt-dlp extraction in `asyncio.to_thread` so the event loop stays unblocked while deno runs YouTube's JS challenge solver.

The proxy routes open a streaming `httpx` response with `stream=True`, forward `Range` headers, strip hop-by-hop response headers (`Connection`, `Keep-Alive`, `Transfer-Encoding`, ...) plus `Set-Cookie`/`Server`/`Alt-Svc` to avoid leaking YouTube fingerprints, and pipe bytes back to the client via `aiter_bytes()`. The response is closed in a `finally` block in the body iterator.

### Why yt-dlp?

An earlier version used the [`innertube`](https://github.com/tombulled/innertube) library. As of 2026 every `innertube` client type returns `UNPLAYABLE` or HTTP 400 for player calls — YouTube hardened against unauthenticated raw-InnerTube access. The next version used `pytubefix`, which bundled a Node binary for JS-based cipher deobfuscation.

Measured 2026-09-24: `pytubefix` was blocked on 14 of 15 playable ids (`YOUTUBE_BLOCKED`);
`yt-dlp` played all 13 VODs plus 2 live streams, and search p50 dropped from 5.32 s to
1.28 s with 90–100% titled hits (was 0–5%, issue #14; cold video lookup ~2.3 s p50).
`yt-dlp` replaced `pytubefix` entirely — video details, search, channel, playlist, and
the live HLS master manifest all go through it now. Full measurement: see
[docs/dev/ytdlp-spike-report.md](dev/ytdlp-spike-report.md).

`yt-dlp` needs the deno JavaScript runtime on PATH to solve YouTube's challenges (the
Docker image ships it via `denoland/deno:bin-2.9.7`); the app logs one ERROR at startup
if deno is missing. The dependency is `yt-dlp[default]`, which pulls in `yt-dlp-ejs`
(the challenge solver scripts) — without it extraction logs "n challenge solving
failed".

If yt-dlp breaks (it eventually will), the fix lives in `app/adapters/youtube.py` only.

## Frontend

Svelte 5 + Vite + TypeScript single-page app.

### Module layout

```
frontend/src/
├── main.ts                  bootstrap
├── App.svelte               Setup gate + nav + router outlet + Player
├── routes.svelte.ts         hand-rolled hash router (Svelte 5 runes)
├── app.css                  CSS vars + base reset
├── lib/
│   ├── api.ts               Single fetch site; injects bearer; 401 invalidates
│   ├── store.svelte.ts      Singleton AppStore (Svelte 5 $state runes)
│   ├── format.ts            Duration/views/bitrate formatters
│   ├── pickAudio.ts         opus > aac, highest bitrate
│   └── types.ts             Hand-mirrored backend Pydantic shapes
├── components/
│   ├── Setup.svelte         First-run bearer token paste
│   ├── SearchBar.svelte
│   ├── ResultList.svelte
│   ├── ResultItem.svelte
│   ├── QueueItem.svelte
│   ├── Spinner.svelte
│   └── Player.svelte        Persistent <audio> with Media Session API
└── pages/
    ├── Search.svelte
    ├── Video.svelte         Format picker + Play/Enqueue
    ├── Queue.svelte
    └── Settings.svelte
```

### Frontend invariants

1. `fetch` is called in exactly one file: `src/lib/api.ts`
2. App state mutations go through `store.svelte.ts` methods (`enqueue`, `next`, `setToken`, etc.)
3. `<Player>` owns the single `<audio>` element; lives in `App.svelte` outside the router so it survives route changes

### State model

```typescript
class AppStore {
  settings = $state<{ bearerToken; defaultQuality; musicOnly }>(...);
  queue = $state<Track[]>(...);    // upcoming tracks
  history = $state<Track[]>(...);  // played tracks, most recent last (cap 50)
  player = $state<{ current: Track | null; isPlaying: boolean; positionSeconds: number; ... }>(...);
  // methods: setToken, enqueue, playNow, next, previous, startPositionFor, setPosition, ...
}
```

Persistence (debounced 200 ms to localStorage):

| Key | Contents |
|---|---|
| `hum.queue`, `hum.history` | `Track[]` through `stripSignedUrls()` |
| `hum.current` | `{ track, pos }` — the playing track (stripped) and its last known position |
| `hum.bookmarks` | `{ [videoId]: { pos, at } }` — resume points for VOD ≥ 10 min (`lib/bookmarks.ts`) |
| `hum.bearer`, `hum.defaultQuality`, `hum.musicOnly`, `hum.normalize` | settings |

`stripSignedUrls()` is the single place signed URLs (`audioUrl`, `hlsUrl`,
`liveStreamUrl`) and `_formats` are removed, on write and on rehydrate. A track
restored from `hum.current` comes back **paused** (`isPlaying: false`, which the
`<audio autoplay>` binding reads) and seeks to its saved position once its fresh
URL loads. `store.startPositionFor(t)` answers "where does this track start":
restored position (once), else a bookmark for long VOD, else 0.

`previous()` goes back to the last history entry when the current track has
played ≤ 3 s, otherwise restarts it; the track being left goes to the front of
the queue. `queue` keeps meaning "upcoming" so its consumers didn't change.

Per-kind behaviour (VOD vs live) lives in `lib/contentKind.ts`; see CLAUDE.md
landmines.

### Player lifecycle

```
ResultItem click → router.navigate('/video/:id')
                 → Video page calls api.video(id)
                 → pickAudio() picks best format
                 → store.playNow(track) OR store.enqueue(track)
                 → Player's $effect updates <audio src>, autoplay
                 → on 'loadedmetadata': seek to store.startPositionFor(track)
                 → every 5 s / on pause / pagehide: store.setPosition + bookmark
                 → on 'ended': clear bookmark, store.next()
                 → on 'error': probe /health → unreachable toast, OR
                   codec swap → refetch + restore position
```

Media Session: metadata + play/pause/next/previous on every track;
`seekto`/`seekbackward`/`seekforward` and `setPositionState` for VOD only
(cleared for live) so lock-screen and headset controls get a scrubbable bar.

URL-expiry recovery is tracked by a `Set<videoId>` so a persistently-broken track doesn't infinite-retry across recovery attempts.

### Routing

Hand-rolled hash router (~25 LOC). State is `$state(read())` updated on `hashchange`. `App.svelte` renders `{@const Page = router.match.component}` and passes `router.match.params` as props.

## Tuning constants (reasoned, not measured)

Every value below was argued for, not measured against real listening or
network conditions. Collected here so that stays visible — tune them against
observed behaviour, and don't defend one just because it shipped.

| Constant | Value | Location | What it decides |
|---|---|---|---|
| `_CACHE_MAX_TTL` | 3600 s | `app/adapters/youtube.py` | Upper bound on trusting YouTube's `expire=` for a cached stream URL |
| `_MASTER_CACHE_TTL_S` | 2 s | `app/api/live.py` | How long a live master manifest is reused |
| `_TARGET_SEGMENT_SECONDS` | 60 s | `app/api/hls.py` | Segment coalescing target for VOD HLS wrapping |
| `upstream_connect_timeout` / `upstream_read_timeout` | 10 s / 30 s | `app/config.py` | Per-phase upstream timeouts (no total timeout, by design) |
| `liveSyncDuration` / `liveMaxLatencyDuration` | 15 s / 30 s | `Player.svelte` (hls.js) | Live start distance from edge / tolerated lag |
| hls.js load policies | TTFB 8 s; load 20 s (manifest) / 30 s (fragment); 4 retries | `Player.svelte` | When a live fetch counts as failed |
| `PERSIST_DEBOUNCE_MS` | 200 ms | `store.svelte.ts` | localStorage write coalescing |
| `HISTORY_MAX` | 50 | `store.svelte.ts` | How far back "previous" can go |
| `PREVIOUS_RESTART_THRESHOLD_S` | 3 s | `store.svelte.ts` | Previous = restart vs go back |
| `BOOKMARK_MIN_DURATION_S` | 600 s | `lib/bookmarks.ts` | Which videos get a resume point |
| `BOOKMARK_END_MARGIN_S` | 30 s | `lib/bookmarks.ts` | How close to the end counts as finished |
| `BOOKMARK_MAX_ENTRIES` | 200 | `lib/bookmarks.ts` | Resume points kept (oldest evicted) |
| `POSITION_SAVE_INTERVAL_MS` | 5000 ms | `Player.svelte` | Worst-case position loss on a crash |
| `SEEK_STEP_S` | 10 s | `Player.svelte` | Lock-screen seek step when the OS gives none |

## Dev / build / deploy

### Local dev

```bash
./scripts/dev.sh
# vite on :5173 (with /api + /proxy + /health proxied to :8000)
# uvicorn --reload on :8000
# open http://127.0.0.1:5173
```

### Production build

```bash
./scripts/build.sh        # frontend/dist/
uvicorn app.main:app      # single process on :8000
```

FastAPI's `app/static.py` mounts `/assets` directly and falls back unknown paths to `index.html` for SPA routing. Reserved prefixes (`api/`, `proxy/`, `health`, `docs`, `redoc`, `openapi.json`) bypass the fallback so a missing API route returns 404 instead of HTML.

### Docker

Two-stage build → single image on port 8000. Healthcheck pings `/health`.

```bash
docker build -t hum .
docker run -p 8000:8000 --env-file .env hum
```

## Testing

| Suite | Command | What it covers |
|---|---|---|
| Backend unit | `pytest tests/unit` | mocked yt-dlp boundary (`_make_ydl`); auth, config, range, models, routes, invariants |
| Backend integration | `pytest -m integration` | 5 tests; hits real YouTube; opt-in |
| Frontend unit + component | `cd frontend && npm test` | mocked fetch + adapter; runes, API, store, components |

All three suites currently green. `ruff check app` and `mypy app` both clean. `svelte-check` reports 0 errors.

## Non-goals (explicit)

- Multi-user / auth beyond a single bearer
- Rate limiting
- PWA / offline service worker
- Audio downloads
- Synced lyrics
- Radio / similar tracks
- Dynamic theming from artwork
- DASH / HLS adaptive streaming
- Gapless playback / crossfade
- Equalizer / visualizer
- Video playback in the UI (proxy exists; UI doesn't surface it)
- Codegen for TS types from Pydantic
- Workspace tooling (npm/pnpm workspaces)
