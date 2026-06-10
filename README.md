# Hum

[![CI](https://github.com/betmoar/streamtube/actions/workflows/ci.yml/badge.svg)](https://github.com/betmoar/streamtube/actions/workflows/ci.yml)

**Sound, at home.**

Hum turns YouTube into a personal audio streamer. Self-hosted, locally run, designed to feel like the music app you wish came built into your home.

Cast to any device on your network, queue up videos as if they were tracks, and let the server do the rest. No accounts, no ads, no telemetry.

Single-user FastAPI backend with bearer-token API auth and Blake3-signed stream URLs. Lean Svelte 5 frontend served from the same process in production.

## Quick start

```bash
git clone <repo>
cd hum

cp .env.example .env
python -c "import secrets; print('API_BEARER_TOKEN=' + secrets.token_urlsafe(32))" >> .env
python -c "import secrets; print('STREAM_SIGNING_KEY=' + secrets.token_hex(32))" >> .env

python3.11 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

uvicorn app.main:app --reload
```

## Frontend

A lean Svelte 5 + Vite + TypeScript single-page app lives in `frontend/`. In production, FastAPI serves the built `frontend/dist/` at `/`; the API stays mounted at `/api/*` and `/proxy/*`.

### Dev (two processes)

```bash
./scripts/dev.sh
# vite on :5173 (with /api + /proxy proxied to :8000)
# uvicorn on :8000
# open http://127.0.0.1:5173
```

### Production build

```bash
./scripts/build.sh        # builds frontend/dist/
uvicorn app.main:app      # serves dist/ at / plus the API
# open http://127.0.0.1:8000
```

### Frontend auth

The frontend prompts for the bearer token on first load and stores it in `localStorage`. Stream proxy URLs are pre-signed by the backend; the `<audio>` element loads them directly.

### Frontend tests

```bash
cd frontend
npm test           # vitest unit + component (42 tests)
```

## Endpoints

All `/api/*` endpoints require `Authorization: Bearer <API_BEARER_TOKEN>`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/search?q=...&limit=20&category=music&live=false` | Search videos (optional music/live filters) |
| GET | `/api/radio?limit=20` | Currently-live music streams (filtered live search) |
| GET | `/api/video/{id}` | Video metadata + signed proxy URLs |
| GET | `/api/channel/{id}` | Channel info |
| GET | `/api/playlist/{id}` | Playlist with items |
| GET | `/api/hls/{id}.m3u8?itag&exp&sig` | HLS byterange wrapper over fMP4/AAC audio (Safari seeking) |
| GET | `/api/live/{id}/manifest.m3u8?exp&sig` | Proxied live-stream HLS playlist (rewritten segment URIs) |
| GET | `/proxy/audio/{id}?itag&exp&sig` | Audio stream (signed, range-aware) |
| GET | `/proxy/stream/{id}?itag&exp&sig` | Video stream (signed, range-aware) |
| GET | `/proxy/thumbnail/{id}?itag=0&exp&sig` | Thumbnail (signed) |
| GET | `/proxy/live-segment/{id}?u&exp&sig` | Live HLS segment proxy (signed, host-allowlisted) |
| GET | `/health` | Health check |

Proxy URLs are minted by `/api/video/{id}` — call it first, hand the returned URLs to your player. For AAC (`audio/mp4`) formats it additionally returns an `hls_url`; for live videos it returns a signed `live_stream_url` manifest. A bearer-protected `/api/debug/live/{id}/upstream` endpoint exposes the raw upstream playlists for live-stream debugging.

## Testing

```bash
pytest                  # fast unit tests (mocked; ~0.5s)
pytest -m integration   # hits real YouTube (5 tests, ~5s)
pytest -m ''            # everything
```

## Configuration

See [.env.example](.env.example). All settings via environment variables.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `API_BEARER_TOKEN` | yes | — | Bearer token for `/api/*` (>=16 chars) |
| `STREAM_SIGNING_KEY` | yes | — | 32-byte hex Blake3 signing key |
| `STREAM_URL_TTL_SECONDS` | no | 21600 | Signed URL TTL (6h) |
| `HOST` | no | 127.0.0.1 | Bind host |
| `PORT` | no | 8000 | Bind port |
| `CORS_ORIGINS` | no | `http://127.0.0.1,http://localhost` | Comma-separated allowed origins |
| `LOG_LEVEL` | no | INFO | stdlib logging level |
| `LOG_JSON` | no | false | JSON-format log lines |
| `DEBUG` | no | false | Enables /docs route |

## Architecture

Ports-and-adapters layout. Three load-bearing invariants:

1. `pytubefix` is imported in exactly one file: `app/adapters/youtube.py`
2. Upstream HTTP goes through exactly one `httpx.AsyncClient` in `app/adapters/upstream_http.py`
3. Stream URLs handed to clients are always Blake3-HMAC-signed; raw YouTube CDN URLs never leave the proxy

Directory tree (`app/`):

```
app/
├── main.py               FastAPI app, lifespan, exception handler, CORS, mount
├── config.py             Pydantic settings
├── auth.py               Bearer + Blake3 URL signing
├── models.py             Pydantic response shapes
├── adapters/
│   ├── youtube.py        Only file that imports pytubefix
│   └── upstream_http.py  Shared httpx.AsyncClient + YouTube host allowlist
├── api/                  GET routes: search, radio, video, channel, playlist, hls, live
├── proxy/                GET routes: audio, video, thumbnail, live-segment (range pass-through)
├── hls/                  sidx box parsing for the fMP4 byterange HLS wrapper
└── live/                 HLS master/media playlist parsing + segment-URI rewriting
```

## Why pytubefix?

An earlier version used the `innertube` Python library. As of mid-2026, all `innertube` client types return `UNPLAYABLE` or HTTP 400 for player calls — YouTube has hardened against unauthenticated raw-InnerTube access. `pytubefix` bundles a Node binary to handle JS-based cipher deobfuscation, which is currently the only way to extract working stream URLs without a full browser.

If pytubefix breaks (it eventually will), the fix lives in `app/adapters/youtube.py` only.

## Limitations

- Single uvicorn worker is correct at this scale (single user)
- No rate limiting beyond the bearer token gate
- In-memory stream URL cache only (capped at 1h, bounded by YouTube's own `expire=`); restart loses it
- Not for public deployment without further hardening
- pytubefix is reverse-engineered; YouTube can break it without notice

## License

MIT
