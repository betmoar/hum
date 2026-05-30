# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/betmoar/streamtube/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/betmoar/streamtube/releases/tag/v0.1.0
