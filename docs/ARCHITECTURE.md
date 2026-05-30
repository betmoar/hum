# Hum Architecture

Lean self-hosted YouTube proxy + lightweight Svelte 5 frontend. Single process, single binary deployment.

## Overview

```
┌─────────────┐     bearer-auth     ┌─────────────┐
│  Frontend   │ ─────────────────▶  │   FastAPI   │
│ (Svelte 5)  │ ◀─── signed URL ─── │   Backend   │
└─────────────┘                     └─────┬───────┘
       │                                  │
       │ <audio src="signed URL">         │ pytubefix.YouTube(...)
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

1. `pytubefix` is imported in exactly one file: [app/adapters/youtube.py](../app/adapters/youtube.py)
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
│   ├── youtube.py        Only file that imports pytubefix
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

The adapter's `resolve_upstream_url(video_id, itag)` returns the YouTube CDN URL. Backed by a process-level in-memory cache `(video_id, itag) → (url, expiry_epoch)` with TTL = `min(YouTube's expire param, 1 hour)`. Cache misses fall through to a fresh `pytubefix.YouTube(...)` call wrapped in `asyncio.to_thread` so the event loop stays unblocked while Node runs the cipher deobfuscation.

The proxy routes open a streaming `httpx` response with `stream=True`, forward `Range` headers, strip hop-by-hop response headers (`Connection`, `Keep-Alive`, `Transfer-Encoding`, ...) plus `Set-Cookie`/`Server`/`Alt-Svc` to avoid leaking YouTube fingerprints, and pipe bytes back to the client via `aiter_bytes()`. The response is closed in a `finally` block in the body iterator.

### Why pytubefix?

An earlier version used the [`innertube`](https://github.com/tombulled/innertube) library. As of 2026 every `innertube` client type returns `UNPLAYABLE` or HTTP 400 for player calls — YouTube hardened against unauthenticated raw-InnerTube access. `pytubefix` bundles a Node binary (via `nodejs-wheel-binaries`) to handle JS-based cipher deobfuscation, which is currently the only way to extract working stream URLs without a full browser.

If pytubefix breaks (it eventually will), the fix lives in `app/adapters/youtube.py` only.

## Frontend

Svelte 5 + Vite + TypeScript single-page app.

### Module layout

```
frontend/src/
├── main.ts                  bootstrap
├── App.svelte               Setup gate + nav + router outlet + Player
├── routes.ts                ~25-LOC hand-rolled hash router
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
  settings = $state<{ bearerToken: string | null }>(...);
  queue = $state<Track[]>(...);
  player = $state<{ current: Track | null; isPlaying: boolean; positionSeconds: number }>(...);
  // methods: setToken, invalidateToken, enqueue, playNow, next, remove, reorder, clear
}
```

Persistence: `queue` + `bearerToken` debounced (200ms) to localStorage. `positionSeconds` deliberately not persisted — restart resumes from 0.

### Player lifecycle

```
ResultItem click → router.navigate('/video/:id')
                 → Video page calls api.video(id)
                 → pickAudio() picks best format
                 → store.playNow(track) OR store.enqueue(track)
                 → Player's $effect updates <audio src>, autoplay
                 → on 'ended': store.next()
                 → on 'error' (signed URL expired): refetch + restore position
```

URL-expiry recovery is tracked by a `Set<videoId>` so a persistently-broken track doesn't infinite-retry across recovery attempts.

### Routing

Hand-rolled hash router (~25 LOC). State is `$state(read())` updated on `hashchange`. `App.svelte` renders `{@const Page = router.match.component}` and passes `router.match.params` as props.

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
| Backend unit | `pytest tests/unit` | 49 tests; mocked InnerTube boundary; auth, config, range, models, routes |
| Backend integration | `pytest -m integration` | 5 tests; hits real YouTube; opt-in |
| Frontend unit + component | `cd frontend && npm test` | 42 tests; mocked fetch + adapter; runes, API, store, components |

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
- CI pipeline / GitHub Actions
- Codegen for TS types from Pydantic
- Workspace tooling (npm/pnpm workspaces)
