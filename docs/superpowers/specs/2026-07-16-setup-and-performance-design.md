# Setup simplification & performance quick wins — design

Date: 2026-07-16
Status: approved (brainstorm + review panel), pending implementation plan

## Problem

1. **Setup is tedious**: the README quick-start is 7 manual steps (clone, cp .env,
   two secret-gen commands, venv, pip install, uvicorn) on a pip/venv flow that
   contradicts the rest of the repo (uv.lock is committed; check.sh requires uv).
   The frontend needs a separate npm install.
2. **Runtime feels slow**: `/api/video/{id}` runs a full pytubefix fetch (HTTPS +
   Node cipher deobfuscation) on every call — replaying a track or revisiting a
   video pays full cost. Search results are never cached. The dev loop re-runs
   `uv sync`, coverage, svelte-check, and a full vite build on every gate run.

Scope decisions (settled with maintainer):
- Setup: **both** a Docker path and a one-command uv script; README leads with
  them, manual pip flow demoted to a footnote.
- Runtime: **quick wins only** — in-memory caches following the existing
  `_stream_url_cache` conventions. No prefetch, no persistent cache.

## Section 1 — Setup simplification

### Secret generation is host-side, in `scripts/setup.sh` (both paths share it)

A container entrypoint that generates `.env` was considered and rejected: the
image runs as non-root `hum` (Dockerfile `USER hum`) which cannot write
`/app/.env`, and compose's `env_file: .env` resolves on the **host** before the
container starts — an entrypoint-written file can't feed it. Host-side
generation avoids both problems and keeps secrets visible/editable on the host.

`scripts/setup.sh`:
- If `.env` is missing: create it from `.env.example`.
- For each required key (`API_BEARER_TOKEN`, `STREAM_SIGNING_KEY`) whose value
  is blank or absent: **replace the blank value in place** (never append —
  `.env.example` already contains `KEY=` lines, and appending would create
  duplicate keys whose winner depends on dotenv parse order). Existing
  non-blank values are never touched. Idempotent: a second run is a no-op.
- Needs only `python3` on PATH for secret generation (no venv required yet).
- Then: `uv sync --extra dev` (backend) and `npm --prefix frontend ci`
  (frontend).
- Flags:
  - `--secrets-only`: stop after `.env` is written (the Docker path).
  - `--dev`: chain into `scripts/dev.sh`.
  - `--prod`: run `scripts/build.sh`, then `uv run hum` (the console script
    from pyproject `[project.scripts]`; binds per HOST/PORT in `.env`).

### Path A: Docker

```
./scripts/setup.sh --secrets-only   # writes .env on the host
docker compose up                   # compose env_file feeds the container
```

Two commands. `docker-compose.yml` keeps `env_file: .env` (unchanged); no
entrypoint script, no secret volume. The image already builds the frontend in
stage 1.

### Path B: uv local

```
./scripts/setup.sh --dev    # secrets + uv sync + npm ci + dev servers
```

README quick-start switches from `python3.11 -m venv` + `pip install` to these
two paths — consistent with check.sh and faster (uv installs from the committed
uv.lock). Manual pip flow becomes a footnote.

### Acceptance (Section 1)

- Fresh clone: `setup.sh` produces a `.env` where both required keys are
  non-blank and pass `app/config.py` validation (token ≥16 chars, key 64 hex).
- Second run of `setup.sh`: `.env` byte-identical (idempotency).
- Pre-set values in `.env` are preserved.
- No duplicate `KEY=` lines ever exist in the produced `.env`.

### Non-goals (Section 1)

No new config format, no secret manager, no clobbering existing `.env` values,
no container-side secret generation. `.env` stays gitignored (verified:
.gitignore line 106). Malformed-but-present values (e.g. a 3-char token) are
not repaired by setup.sh — the app's own validators reject them at startup
with a clear error; that's the intended surface.

## Section 2 — Runtime quick wins

All in `app/adapters/youtube.py`, following the `_stream_url_cache`
conventions: module-level dicts, single GIL-atomic dict ops, written from
`asyncio.to_thread` workers, read from the event loop. One deliberate, bounded
departure is called out in 2a. Invariant tests are unaffected (they check
imports, client count, route auth — not runtime state).

### 2a. VideoDetails metadata cache

- `video_id -> (VideoDetails, expiry)`. `video()` checks before dispatching to
  `_fetch_video`.
- **Single-flight on miss**: concurrent `video()` misses for the same id
  collapse onto one fetch via the same keyed in-flight-task pattern
  `_refresh_cache_once` already uses (`_inflight_refresh`). Without this, a
  burst of identical calls each pays the pytubefix cost the cache exists to
  avoid.
- TTL: `min(VIDEO_CACHE_TTL_SECONDS, _CACHE_MAX_TTL)` — the clamp exists for
  **metadata freshness** (title/duration/views drift; a stale entry also keeps
  serving formats YouTube may no longer offer). Note the cached proxy paths
  themselves are unsigned and stable — there is no expiry coupling to the
  stream-URL cache; `resolve_upstream_url` refreshes CDN URLs independently.
- Cached objects hold **unsigned** proxy paths exactly as `_fetch_video`
  produces today; `/api/video` signs per request, unchanged.
- **Deep-copy on hit**: `/api/video` mutates the returned `VideoDetails` when
  signing (`af.url = sign_format_url(...)`). Serving the same cached instance
  twice would sign an already-signed URL. `video()` returns
  `details.model_copy(deep=True)` on cache hit; the cache keeps the canonical
  unsigned copy. This is the one departure from the pure single-dict-op
  pattern: the copy is built from a reference read once, so a concurrent
  writer replacing the entry can't corrupt it.
- **Live videos never cached** — necessarily a **post-fetch** check
  (`is_live` is only knowable after the fetch): a live result is returned but
  not stored, so live videos pay full pytubefix cost on every call. Accepted —
  live is a niche path here, and live state (broadcast ended, manifest
  availability) goes stale fast.
- **Errors are not cached** (no negative caching): a failed fetch re-fetches
  on the next call. Accepted for simplicity.

### 2b. Search result cache

- `(query, category, live, limit) -> (list[SearchHit], expiry)`,
  TTL `SEARCH_CACHE_TTL_SECONDS` (default 300 s).
- Search hits carry no signed URLs and no expiry coupling — safe to cache.
- **Eviction runs on search-cache write** (see 2c) — a search-only session
  never triggers `_refresh_cache`, so relying on the existing sweep alone
  would let this dict grow unbounded.

### 2c. Eviction

- Extend `_evict_expired()` to sweep all three dicts.
- Call sites: after `_refresh_cache` (as today) **and** after each search-cache
  write (in the `to_thread` worker, off the event loop — search writes already
  happen there). Both sites are off the request hot path for cache hits.
- No max-size cap beyond TTL eviction — single-user LAN app; stated and
  accepted.

### Config

Two new settings in `app/config.py` with defaults (so they stay optional),
documented in `.env.example` and the README settings table:

| Setting | Default | Notes |
|---|---|---|
| `VIDEO_CACHE_TTL_SECONDS` | 3600 | effective TTL = `min(setting, _CACHE_MAX_TTL=3600)`; the clamp constant stays module-level, not configurable |
| `SEARCH_CACHE_TTL_SECONDS` | 300 | |

### Testing (Section 2)

Unit tests (existing monkeypatched-factory style):
- hit / miss / expiry for both caches; expiry uses injected `now` where the
  existing tests do.
- single-flight: N concurrent `video()` misses for one id → exactly one
  `_fetch_video` call.
- deep-copy-on-hit: two sequential signed `/api/video` responses are
  independently signed AND the cached entry's URLs still contain no `sig=`
  after hits were served.
- clamp: `VIDEO_CACHE_TTL_SECONDS` set above `_CACHE_MAX_TTL` → effective
  expiry clamped.
- live bypass: `is_live=True` result returned but absent from the cache.
- eviction: expired entries in all three dicts dropped by the sweep; sweep
  fires on search-cache write.

### What this buys / doesn't

Replay, revisit, and repeat-search within TTL skip pytubefix entirely.
First-play cost is unchanged — inherent to pytubefix, out of scope.

## Section 3 — Dev loop speed

`check.sh` remains THE pre-push gate and keeps running the same checks CI runs.
(Note: CI does **not** invoke check.sh — `.github/workflows/ci.yml` runs its
own equivalent steps; check.sh mirrors them. Nothing here touches CI.)

### 3a. `check.sh fast` mode

New mode, mutually exclusive with `all|backend|frontend` (same single-arg
parsing as today): `./scripts/check.sh fast` — the between-edits inner-loop
command, not a pre-push substitute. Runs:
- `uv run --no-sync ruff check .`
- `uv run --no-sync mypy app/ --strict` (incremental cache makes reruns cheap)
- `uv run --no-sync pytest -q` (no `--cov` — coverage instrumentation is pure
  overhead mid-loop)
- `npm --prefix frontend test` (vitest only; no svelte-check, no vite build)

`uv run --no-sync` is the load-bearing detail: plain `uv run` re-syncs on a
stale lockfile (defeating the point), and bare tool names would require an
activated venv. Fast mode assumes a previously-synced env; if `.venv` is
missing it fails with uv's own clear error.

### 3b. Staleness-guarded `uv sync` in the full gate

Only run `uv sync --extra dev` when `uv.lock` or `pyproject.toml` is newer than
a stamp file (`.venv/.sync-stamp`, touched after successful sync). When deps
changed (or the stamp is absent — fresh clone, `rm -rf .venv`), behavior is
identical to today. The full gate's *checks* are unchanged; only the redundant
no-op sync is skipped. CI is unaffected because CI doesn't call check.sh.

### 3c. `dev.sh` reload scoping

`uvicorn --reload` currently watches the whole CWD, so frontend edits restart
the backend. Add `--reload-dir app`. Intended side effect: edits outside
`app/` (`.env`, `pyproject.toml`, scripts) no longer trigger backend reload —
restart dev.sh for those.

### Out of scope (Section 3, decided)

No pytest-xdist (negative value on a ~1 s suite), no mypy daemon, no frontend
build-tool changes.

## Files touched (summary)

| File | Change |
|---|---|
| `scripts/setup.sh` | new — secrets (in-place fill) + sync + npm ci; `--secrets-only/--dev/--prod` |
| `README.md` | lead with the two paths; pip flow → footnote; settings table gains 2 rows |
| `app/adapters/youtube.py` | video + search caches, single-flight on video miss, eviction sweep |
| `app/config.py` | `VIDEO_CACHE_TTL_SECONDS`, `SEARCH_CACHE_TTL_SECONDS` |
| `.env.example` | document new settings |
| `scripts/check.sh` | `fast` mode (`uv run --no-sync`); sync staleness guard |
| `scripts/dev.sh` | `--reload-dir app` |
| `tests/unit/` | cache behavior tests (see Testing, Section 2) |

Unchanged (explicitly): `Dockerfile`, `docker-compose.yml` (host-side secret
gen made the entrypoint redesign unnecessary), `.github/workflows/ci.yml`.

## Clarifications (2026-07-16)

Review-panel round (3 GLM lenses; full report in
`.review-panel/2026-07-16-setup-and-performance-design.md`):

- **Q (lens B):** Docker path infeasible as first drafted (non-root `hum` can't
  write `/app/.env`; compose `env_file:` resolves host-side before the
  entrypoint runs) — which redesign? → **A:** Host-side generation:
  `setup.sh --secrets-only` then `docker compose up`; no entrypoint.
- **Q (lens A):** Add single-flight to the metadata cache so concurrent
  identical misses don't each fire pytubefix? → **A:** Yes — reuse the
  existing keyed in-flight-task pattern.
- **Q (lens B):** Live bypass is necessarily post-fetch, so live videos pay
  full cost every call — accept or add a short live TTL? → **A:** Accept full
  cost; spec states the post-fetch discard explicitly.
