# Hum

[![CI](https://github.com/betmoar/hum/actions/workflows/ci.yml/badge.svg)](https://github.com/betmoar/hum/actions/workflows/ci.yml)

**Sound, at home.**

Hum turns YouTube into a personal audio streamer. Self-hosted, locally run, designed to feel like the music app you wish came built into your home.

Cast to any device on your network, queue up videos as if they were tracks, and let the server do the rest. No accounts, no ads, no telemetry.

Single-user FastAPI backend with bearer-token API auth and Blake3-signed stream URLs. Lean Svelte 5 frontend served from the same process in production.

## Quick start

Both paths start with:

```bash
git clone <repo>
cd hum
```

### Docker

```bash
./scripts/setup.sh --secrets-only   # writes .env with generated secrets
docker compose up
```

Open http://127.0.0.1:8000.

### Local (uv)

Requires [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
./scripts/setup.sh --dev    # secrets + backend/frontend deps + dev servers
```

Open http://127.0.0.1:5173 (vite dev server; API on :8000).

Production-style single process: `./scripts/setup.sh --prod` builds
`frontend/dist/` and serves everything on :8000.

<details>
<summary>Manual setup (what setup.sh does)</summary>

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # -> API_BEARER_TOKEN in .env
python3 -c "import secrets; print(secrets.token_hex(32))"      # -> STREAM_SIGNING_KEY in .env
uv sync --extra dev
npm --prefix frontend ci
uv run uvicorn app.main:app --reload
# without uv: python3.11 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'
```
</details>

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
npm test           # vitest unit + component
```

## Endpoints

All `/api/*` endpoints require `Authorization: Bearer <API_BEARER_TOKEN>`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/search?q=...&limit=20` | Search videos |
| GET | `/api/video/{id}` | Video metadata + signed proxy URLs |
| GET | `/api/channel/{id}` | Channel info |
| GET | `/api/playlist/{id}` | Playlist with items |
| GET | `/proxy/audio/{id}?itag&exp&sig` | Audio stream (signed, range-aware) |
| GET | `/proxy/stream/{id}?itag&exp&sig` | Video stream (signed, range-aware) |
| GET | `/proxy/thumbnail/{id}?itag=0&exp&sig` | Thumbnail (signed) |
| GET | `/health` | Health check |

Proxy URLs are minted by `/api/video/{id}` — call it first, hand the returned URLs to your player.

## Testing

```bash
./scripts/check.sh      # THE pre-push gate — mirrors CI exactly (backend + frontend)
pytest                  # fast unit tests (mocked; ~1s)
pytest -m integration   # hits real YouTube (5 tests, ~5s)
pytest -m ''            # everything
```

Maintainer docs: [CLAUDE.md](CLAUDE.md) (mental model + landmines),
[docs/PLAYBOOKS.md](docs/PLAYBOOKS.md) (procedures), [docs/BACKLOG.md](docs/BACKLOG.md)
(known debt).

## Configuration

See [.env.example](.env.example). All settings via environment variables.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `API_BEARER_TOKEN` | yes | — | Bearer token for `/api/*` (>=16 chars) |
| `STREAM_SIGNING_KEY` | yes | — | 32-byte hex Blake3 signing key |
| `STREAM_URL_TTL_SECONDS` | no | 21600 | Signed URL TTL (6h) |
| `VIDEO_CACHE_TTL_SECONDS` | no | 3600 | Video metadata cache TTL, seconds (capped at 1h by the adapter) |
| `SEARCH_CACHE_TTL_SECONDS` | no | 300 | Search result cache TTL, seconds |
| `PLAYLIST_CACHE_TTL_SECONDS` | no | 300 | Playlist listing cache TTL, seconds (capped at 1h by the adapter) |
| `HOST` | no | 127.0.0.1 | Bind host |
| `PORT` | no | 8000 | Bind port |
| `CORS_ORIGINS` | no | `http://127.0.0.1,http://localhost` | Comma-separated allowed origins |
| `LOG_LEVEL` | no | INFO | stdlib logging level |
| `LOG_JSON` | no | false | JSON-format log lines |
| `DEBUG` | no | false | Enables /docs route |

## Architecture

Ports-and-adapters layout. Three load-bearing invariants:

1. `yt_dlp` is imported in exactly one file: `app/adapters/youtube.py`
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
│   ├── youtube.py        Only file that imports yt_dlp
│   └── upstream_http.py  Shared httpx.AsyncClient + YouTube host allowlist
├── api/                  GET routes: search, video, channel, playlist
└── proxy/                GET routes: audio, video, thumbnail (range pass-through)
```

## Why yt-dlp?

An earlier version used the `innertube` Python library, then `pytubefix`. As of
2026-09-24, `pytubefix` was measured blocked on 14 of 15 playable ids; `yt-dlp` played
all of them and cut search p50 from ~5.3 s to ~1.3 s. yt-dlp needs the
[deno](https://deno.com) JavaScript runtime on PATH (the Docker image ships it via
`denoland/deno:bin-2.9.7`) to solve YouTube's JS challenges.

If yt-dlp breaks (it eventually will), the fix lives in `app/adapters/youtube.py` only.

## Limitations

- Single uvicorn worker is correct at this scale (single user)
- No rate limiting beyond the bearer token gate
- In-memory stream URL cache only (5-min TTL); restart loses it
- Not for public deployment without further hardening
- yt-dlp's YouTube extractor is reverse-engineered; YouTube can break it without notice

## License

MIT
