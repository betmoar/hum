# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-09-24

### Changed

- **`pytubefix` is replaced entirely by `yt-dlp`** — no backend switch, no fallback.
  Video details, search, channel, playlist, and the live HLS master manifest all go
  through `yt-dlp` now; `yt_dlp` is imported in exactly one file
  (`app/adapters/youtube.py`, invariant 1). Measured 2026-09-24: pytubefix was blocked
  on 14 of 15 playable ids (`YOUTUBE_BLOCKED`); yt-dlp played all 13 VODs and 2 live
  streams through the proxy, and search p50 dropped from 5.32 s to 1.28 s with
  90–100% titled hits (was 0–5%, fixes empty search titles, #14). Cold video lookups
  are slower (~2.3 s p50 vs a working pytubefix's ~0.3 s). Needs the
  [deno](https://deno.com) JavaScript runtime on PATH; the Docker image ships it via
  `denoland/deno:bin-2.9.7`, and the app logs one ERROR at startup if deno is missing.
  Channel `subscriber_count` is now populated (yt-dlp `channel_follower_count`).
  Loudness normalisation data (`loudnessDb`) is not available under yt-dlp.

### Added

- **Browse playlists from search**: playlist hits open a playlist page
  (`#/playlist/<id>`) with play-now / enqueue per track plus "Play all" and
  "Enqueue all". Bulk enqueue uses the playlist listing's metadata — no
  per-track `/api/video` call; the signed URL is fetched when a track starts.

### Fixed

- yt-dlp: "This video is unavailable" now maps to 404 `VIDEO_UNAVAILABLE` instead of
  502 `UPSTREAM_FAILURE`.
- Search filters (`category=music`, `live=true`) sent sort-order instead of
  type=Video (protobuf field 1 vs 2), so filtered searches could return nothing
  ("verknipt" + music: 0 results). Live searches now return videos only; music
  searches return videos and (browsable) playlists, no channels.
- Search no longer lists YouTube "Mix" playlists (`RD…` ids): YouTube refuses to
  open them as playlists.
- Error responses no longer echo yt-dlp's raw error text, which can contain
  signed CDN URLs; the raw text goes to the server log.
- A live video without an HLS manifest now fails at `/api/video` with 502
  `LIVE_UNAVAILABLE` instead of returning an unplayable live track.
- `httpx` request logging is capped at WARNING: at INFO it logged every signed
  googlevideo URL, including the server's IP.

### Removed

- `YT_BACKEND` setting, `app/adapters/youtube_ytdlp.py` (absorbed into
  `app/adapters/youtube.py`), and the `pytubefix` dependency along with its
  transitive deps (`aiohttp`, `nodejs-wheel-binaries`) and the Dockerfile's
  pytubefix `__cache__` dir workaround. `scripts/bench_yt_backends.py` and
  `scripts/bench_yt_set.json` are deleted (the pytubefix/yt-dlp comparison is over;
  the result stays in `docs/dev/ytdlp-spike-report.md` as a historical record),
  replaced by `scripts/capture_ytdlp_fixtures.py` for re-capturing yt-dlp test
  fixtures.

## [0.1.2] - 2026-07-29

### Added

- **AirPlay from Safari to AirPlay 2 speakers** (e.g. Sonos): a per-element
  AirPlay button in the player transport routes Hum's audio alone to the
  speaker, replacing the system-wide macOS Sound Output route (which also
  carries notification audio and adds scrubber latency). The button appears in
  both the mini-player and the expanded now-playing overlay, gated on AirPlay
  support and target availability. VOD playback routes over the existing signed
  native-HLS URL; live tracks honestly hide the button (hls.js/MSE output can't
  be AirPlay-routed). Frontend-only — no server changes, the speaker never
  fetches a Hum URL (AirPlay-to-speaker is a source-encoded push). Verified
  end-to-end against a Sonos Move.

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

[Unreleased]: https://github.com/betmoar/hum/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/betmoar/hum/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/betmoar/hum/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/betmoar/hum/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/betmoar/hum/releases/tag/v0.1.0
