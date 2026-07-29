# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-07-29

### Added

- One-command setup: `scripts/setup.sh` (secrets + backend + frontend deps),
  with `--secrets-only` / `--dev` / `--prod` flags. README leads with the Docker
  and uv paths.
- `scripts/check.sh fast` — inner-loop mode (ruff, mypy, pytest without
  coverage, vitest). Not a pre-push substitute. The full gate now skips
  `uv sync` when `uv.lock`/`pyproject.toml` are unchanged.
- Adapter caches for video metadata and search results, with configurable TTLs
  (`VIDEO_CACHE_TTL_SECONDS`, `SEARCH_CACHE_TTL_SECONDS`; both clamped to 1 h).
  Repeat plays and revisited searches skip a full pytubefix fetch.

### Fixed

- Single-flight fetches no longer collapse when one caller disconnects: callers
  await through `asyncio.shield`, so a cancelled request can't cancel the shared
  task other callers are waiting on. Previously an unlucky caller received
  `CancelledError` — a `BaseException` that escapes the global handlers, giving
  the client a torn connection instead of a mapped 4xx/5xx.
- `search()` gained single-flight; concurrent identical queries no longer each
  hit pytubefix.
- `SearchHit` is immutable, so a caller can't mutate a cached hit in place and
  poison later cache reads.
- Expired metadata-cache entries are now swept on the metadata path too; a
  session that only read metadata previously never triggered a sweep.
- `scripts/check.sh fast` fails with a clear message when `.venv` is missing
  instead of creating an empty one and failing on imports.
- Upstream failures no longer surface as bare 500s: pytubefix errors are mapped to
  `YouTubeError` in the adapter and handled globally (`404 VIDEO_UNAVAILABLE`,
  `503 YOUTUBE_BLOCKED`, `502 UPSTREAM_FAILURE` / `UPSTREAM_UNREACHABLE`).
- HLS sidx parser returns a clean fallback (415 → direct stream) instead of crashing
  when the segment index is truncated by the 64 KB head fetch.
- Live tail-trimmed manifests preserve `#EXT-X-ENDLIST`, so players stop polling when
  a broadcast ends.
- Signed `hls_url` is now stripped from the persisted queue (both on write and on
  rehydrate); Safari no longer replays an expired HLS URL after a reload.
- Search results no longer race: a slow earlier query can't overwrite a newer one.
- Non-ASCII bearer tokens return 401 instead of 500.
- Unhandled `play()` promise rejections in the player are caught.

### Security

- Upstream host allowlist is enforced on every redirect hop (SSRF hardening).
- `/api/debug/live/*` is gated on `DEBUG=true` (it exposes raw CDN URLs).
- Docker image runs as a non-root user.

### Added

- Architecture invariants enforced as tests (`tests/unit/test_invariants.py`).
- `scripts/check.sh` — the single pre-push gate mirroring CI.
- Maintainer handoff docs: `CLAUDE.md`, `docs/PLAYBOOKS.md`, `docs/BACKLOG.md`.
- Ruff now lints tests in CI (with test-appropriate ignores).

## [0.1.0] - 2026-05-30

First tagged release of Hum — a self-hosted YouTube audio streamer.

### Added

- **Backend (FastAPI)**: search, video metadata, and channel/playlist endpoints
  backed by a pytubefix adapter isolated behind a ports-and-adapters boundary.
- **Signed streaming**: Blake3-signed, time-limited proxy URLs for audio, video,
  thumbnail, and HLS, with bearer-token API auth (single-user).
- **Audio proxy**: range-aware passthrough so seeking streams by byte range
  rather than downloading whole files.
- **HLS for VOD**: on-the-fly HLS manifest generation for `audio/mp4` streams
  (Safari plays native HLS; other browsers use the direct proxy URL).
- **Live & radio playback**: live HLS via hls.js across all browsers, with a
  master/media playlist parser+rewriter, signed segment passthrough, tail-trim,
  and ad-cue stripping. Radio browsing with live-only filtering.
- **Quality tiers & music filter**: selectable audio quality tiers and a
  music-topic search filter injected via the YouTube `Search.filter` protobuf.
- **Frontend (Svelte 5)**: bottom player with constant-speed marquee title,
  queue, now-playing, search, video detail, and settings; served from the same
  process in production.
- **Stream URL cache**: TTL-bounded cache honoring YouTube's own `expire`, with
  single-flight refresh and expired-entry eviction.
- **Packaging**: multi-stage Dockerfile (frontend build + Python runtime) and
  docker-compose with healthcheck.
- **CI**: GitHub Actions for backend (ruff, mypy --strict, pytest on Python
  3.11/3.12) and frontend (svelte-check, vitest, vite build); tag-triggered
  release workflow.

[Unreleased]: https://github.com/betmoar/hum/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/betmoar/hum/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/betmoar/hum/releases/tag/v0.1.0
