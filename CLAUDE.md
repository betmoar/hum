# Hum — maintainer's handoff

Self-hosted YouTube audio streamer. FastAPI backend + Svelte 5 SPA, one process in
production. Single user, bearer token, Blake3-signed stream URLs. Read this file first;
`docs/ARCHITECTURE.md` has the full map, `docs/PLAYBOOKS.md` has step-by-step procedures
for the recurring jobs, `docs/BACKLOG.md` has known debt.

## Commands

```bash
./scripts/check.sh        # THE gate. Mirrors CI exactly. Run before every push.
./scripts/dev.sh          # dev servers: vite :5173 + uvicorn :8000
./scripts/build.sh        # build frontend/dist for single-process prod
uv run pytest -m integration   # 5 tests against real YouTube (opt-in, needs network)
```

## The three invariants (enforced by tests/unit/test_invariants.py)

1. **`pytubefix` is imported in exactly one file:** `app/adapters/youtube.py`.
   YouTube breaks pytubefix regularly; this keeps the fix a one-file job.
2. **Exactly one `httpx.AsyncClient`**, built in `app/adapters/upstream_http.py`.
   One pool, one timeout policy, one host allowlist (enforced per redirect hop).
3. **Raw YouTube CDN URLs never leave the server.** Everything handed to clients is a
   relative `/proxy/...` or `/api/...` path, signed with Blake3-HMAC and an expiry.
   Every route is either bearer-authed or signature-verified (also test-enforced).

If an invariant test fails, you are probably about to break the design — read the
test's message and `docs/PLAYBOOKS.md` before "fixing" the test.

## Load-bearing map (what breaks everything, in order)

| File | Why it's load-bearing |
|---|---|
| `app/adapters/youtube.py` | The only pytubefix boundary. Stream URL cache + single-flight refresh + error mapping live here. Most fragile file in the repo — YouTube changes underneath it. |
| `app/auth.py` | All four signing schemes (format URL, live manifest, live segment, bearer). A payload-format change invalidates every URL clients hold. |
| `app/adapters/upstream_http.py` | The one HTTP client + host allowlist. All upstream bytes flow through it. |
| `app/proxy/_common.py` | verify → resolve → stream pipeline shared by audio and video proxies. |
| `app/main.py` | Global exception handlers: upstream failures MUST map to 4xx/5xx JSON, never bare 500s. The frontend's recovery logic keys off these statuses. |
| `frontend/src/lib/store.svelte.ts` | All app state + localStorage persistence. Signed URLs must be stripped on persist AND on rehydrate (see comment in `#flush`). |
| `frontend/src/components/Player.svelte` | The single `<audio>` element; VOD src picking, hls.js live path, expiry recovery. |
| `frontend/src/lib/types.ts` | Hand-maintained mirror of `app/models.py`. **If you touch one, update the other.** No codegen (deliberate — see non-goals). |

## Couplings (change X ⇒ update Y)

- `app/models.py` ⇄ `frontend/src/lib/types.ts` (hand-mirrored shapes).
- Signing payload formats in `app/auth.py` ⇄ every URL-minting site
  (`app/api/video.py`, `app/api/live.py`) ⇄ every verifying route. The payload embeds
  the route path (e.g. `/proxy/audio/{id}`) — renaming a route invalidates its URLs.
- `Track` gains a signed-URL field ⇒ strip it in `store.svelte.ts` `#flush()` **and**
  the queue-rehydrate map (both marked with comments).
- New route ⇒ must carry `Depends(require_bearer)` or a `sig` query param, or
  `test_invariant_3_every_route_is_authed_or_signed` fails (public routes go in its
  `_PUBLIC_PATHS` with justification).
- `app/static.py` `_SPA_RESERVED_PREFIXES` ⇒ new top-level API prefixes must be added
  or the SPA fallback swallows their 404s.

## Landmines (things that look wrong but are right, and vice versa)

- **`_is_currently_live` requires `value is True`, not truthiness** — MagicMock-shaped
  test fixtures would otherwise take the live path. Don't "simplify" it.
- **The upstream client has NO total timeout** (connect/read/write only). Long media
  streams are normal; adding a total timeout kills them mid-track.
- **`_stream_url_cache` is written from `asyncio.to_thread` workers** and read from the
  event loop. Single dict ops only (GIL-atomic). Don't add compound read-modify-write.
- **YouTube's `expire=` param is trusted but clamped** to 1 h (`_CACHE_MAX_TTL`). The
  cache can still go stale early (IP change invalidates URLs) — the frontend's
  `handleError` → refetch path is the recovery, keyed by status codes, which is why
  upstream errors must never surface as 500s.
- **Search-hit thumbnails are raw `i.ytimg.com` URLs** loaded directly by the browser;
  only the now-playing thumbnail goes through `/proxy/thumbnail`. A scoped tradeoff:
  proxying every search-grid image would multiply proxy load for a modest privacy gain
  (the browser's IP is exposed to ytimg, but streams stay proxied). Listed in
  `docs/BACKLOG.md` if the privacy posture ever changes.
- **`sign_live_manifest_url` / `sign_live_segment_url` use distinct payload prefixes**
  (`live-manifest|`, `live-segment|`) to prevent cross-protocol signature reuse. Any
  new signed URL type needs its own prefix. See PLAYBOOKS.
- **pytest deselects integration tests by default** (`-m 'not integration'` in
  `pyproject.toml` addopts). CI never talks to YouTube.

## Non-goals (decided, don't re-litigate without cause)

Multi-user auth, rate limiting, DASH/adaptive streaming, downloads, TS codegen from
Pydantic, gapless playback. The app targets one user on a LAN. "Not for public
deployment without further hardening" is a real caveat: the bearer token is a single
shared secret stored in browser localStorage (XSS ⇒ full compromise — top residual
risk in `docs/BACKLOG.md`).

## When YouTube breaks (it will)

Symptom: `/api/video` returns 502/503, `YOUTUBE_BLOCKED` or `UPSTREAM_FAILURE` in logs.
Go to `docs/PLAYBOOKS.md` § "pytubefix broke". Short version: reproduce with
`uv run pytest -m integration`, bump pytubefix, check its issue tracker; the fix is
confined to `app/adapters/youtube.py` by invariant 1.
