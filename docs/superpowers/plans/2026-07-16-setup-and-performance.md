# Setup Simplification & Performance Quick Wins — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-command setup (Docker + uv paths), in-memory video/search caches so repeat actions skip pytubefix, and a faster dev loop (`check.sh fast`, staleness-guarded sync, scoped reload).

**Architecture:** Spec at `docs/superpowers/specs/2026-07-16-setup-and-performance-design.md` (read it first). All runtime caching lives in `app/adapters/youtube.py`, mirroring the existing `_stream_url_cache` conventions (module-level dicts, single GIL-atomic dict ops, single-flight on miss). Setup collapses into a new idempotent `scripts/setup.sh` that fills blank `.env` keys in place. `check.sh` gains a `fast` mode; full-gate checks are unchanged.

**Tech Stack:** Python 3.11, FastAPI, pydantic-settings, pytest (asyncio_mode=auto, monkeypatched pytubefix factories), uv, bash scripts, Svelte 5 frontend (untouched).

## Global Constraints

- NEVER `git push` — the maintainer pushes. Commit per task on the current branch `chore/setup-perf-spec` (already off `main`).
- Stage only files you changed; never blanket `git add <dir>`.
- Gate: `./scripts/check.sh` must be green before claiming done (ruff, mypy --strict, pytest+cov, svelte-check, vitest, vite build).
- ruff: line-length 100, rules `E,F,I,B,UP,N,ANN,SIM,C4`; `app/adapters/youtube.py` may use `Any` (ANN401 ignored there). mypy strict.
- The three invariants in `tests/unit/test_invariants.py` must stay green: pytubefix only in `app/adapters/youtube.py`; one `httpx.AsyncClient`; every route bearer-authed or signed.
- Cache-mutation rule (CLAUDE.md landmine): module-level cache dicts get single dict ops only — no compound read-modify-write. Writers may run in `asyncio.to_thread` workers.
- `app/models.py` shapes are NOT changed by this plan ⇒ `frontend/src/lib/types.ts` needs no update. Do not touch frontend source.
- Repo scripts use `#!/usr/bin/env bash` with `set -euo pipefail` — keep that; write portable bash (macOS BSD sed has no GNU `-i` semantics; use mktemp+mv).
- pytest runs unit tests only by default (`-m 'not integration'`); never require network in unit tests.

---

### Task 1: Cache TTL settings in config

**Files:**
- Modify: `app/config.py` (add two fields after `stream_url_ttl_seconds`, ~line 27)
- Modify: `.env.example` (document new settings)
- Modify: `README.md` (settings table, ~line 95-105)
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `Settings.video_cache_ttl_seconds: int` (default 3600, ge=1) and `Settings.search_cache_ttl_seconds: int` (default 300, ge=1), read via the existing `app.config.get_settings()`. Task 2 and 3 consume these.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_config.py` (match the file's existing import style; add `ValidationError` to the pydantic import if not present):

```python
def test_cache_ttl_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIDEO_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.delenv("SEARCH_CACHE_TTL_SECONDS", raising=False)
    s = Settings(api_bearer_token="x" * 16, stream_signing_key="00" * 32)
    assert s.video_cache_ttl_seconds == 3600
    assert s.search_cache_ttl_seconds == 300


def test_cache_ttl_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        Settings(
            api_bearer_token="x" * 16,
            stream_signing_key="00" * 32,
            video_cache_ttl_seconds=0,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -v -k cache_ttl`
Expected: FAIL — `video_cache_ttl_seconds` not a Settings field (AttributeError / ValidationError for unexpected kwarg with `extra="ignore"` → the defaults test fails on the missing attribute).

- [ ] **Step 3: Add the fields**

In `app/config.py`, directly under `stream_url_ttl_seconds: int = 21600  # 6h`:

```python
    # Caching (adapter-level, in-memory)
    video_cache_ttl_seconds: int = Field(3600, ge=1)   # clamped by adapter _CACHE_MAX_TTL
    search_cache_ttl_seconds: int = Field(300, ge=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: all PASS (new + existing).

- [ ] **Step 5: Document**

Append to `.env.example` under the `# Optional` block:

```
VIDEO_CACHE_TTL_SECONDS=3600
SEARCH_CACHE_TTL_SECONDS=300
```

Add two rows to the README settings table (after `STREAM_URL_TTL_SECONDS`):

```markdown
| `VIDEO_CACHE_TTL_SECONDS` | no | 3600 | Video metadata cache TTL, seconds (capped at 1h by the adapter) |
| `SEARCH_CACHE_TTL_SECONDS` | no | 300 | Search result cache TTL, seconds |
```

- [ ] **Step 6: Commit**

```bash
git add app/config.py tests/unit/test_config.py .env.example README.md
git commit -m "feat(config): video/search cache TTL settings"
```

---

### Task 2: VideoDetails metadata cache with single-flight

**Files:**
- Modify: `app/adapters/youtube.py` (new dicts near `_stream_url_cache` ~line 44; replace `video()` ~line 167; new `_fetch_video_cached` next to `_fetch_video` ~line 268)
- Modify: `tests/conftest.py` (global cache-reset fixture)
- Test: `tests/unit/test_adapter_caches.py` (new file)

**Interfaces:**
- Consumes: `Settings.video_cache_ttl_seconds` (Task 1), existing `_fetch_video`, `_to_thread_mapped`, `_CACHE_MAX_TTL`.
- Produces: module-level `_video_details_cache: dict[str, tuple[VideoDetails, float]]`, `_inflight_video: dict[str, asyncio.Task[VideoDetails]]`, and thread-bound `_fetch_video_cached(video_id: str) -> VideoDetails`. Task 3 extends `_evict_expired` to sweep `_video_details_cache`. Public `video(video_id) -> VideoDetails` signature unchanged.

- [ ] **Step 1: Add the global cache-reset fixture**

The metadata cache makes adapter state leak across tests (e.g. a second `adapter.video()` call in another test would silently hit the cache and skip `_stream_url_cache` population). Reset everything once, globally. Append to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _reset_adapter_caches() -> None:
    """Adapter caches are module-level; clear them between tests so cached
    VideoDetails/search hits from one test can't satisfy another test's call."""
    from app.adapters import youtube as _yt

    _yt._stream_url_cache.clear()
    _yt._inflight_refresh.clear()
    _yt._video_details_cache.clear()
    _yt._search_cache.clear()
    _yt._inflight_video.clear()
```

(`_search_cache` is created in Task 3 — to keep this fixture landing once, create BOTH new dicts in this task's Step 3; Task 3 only adds the search read/write logic.) Leave the existing narrower `reset_cache` fixture in `tests/unit/test_youtube_adapter.py` alone — redundant but harmless.

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_adapter_caches.py`:

```python
"""Tests for the VideoDetails metadata cache (single-flight, deep-copy, live bypass)."""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.adapters import youtube as adapter


def _mock_stream(itag: int, mime_type: str) -> MagicMock:
    s = MagicMock()
    s.itag = itag
    s.mime_type = mime_type
    s.bitrate = 128000
    s.url = f"https://rr1---sn-test.googlevideo.com/videoplayback?itag={itag}"
    s.audio_sample_rate = 44100
    s.width = None
    s.height = None
    s.fps = None
    return s


def _mock_youtube(video_id: str = "dQw4w9WgXcQ") -> MagicMock:
    yt = MagicMock()
    yt.video_id = video_id
    yt.title = "Test Title"
    yt.author = "Test Author"
    yt.channel_id = "UCtest"
    yt.length = 213
    yt.views = 1000
    yt.description = "d"
    yt.vid_info = {"videoDetails": {"isLive": False}}
    streams = [_mock_stream(140, 'audio/mp4; codecs="mp4a.40.2"')]
    sq = MagicMock()
    sq.__iter__ = lambda self: iter(streams)
    yt.streams = sq
    return yt


def _counting_factory(calls: dict[str, int], delay: float = 0.0) -> Any:
    def factory(vid: str) -> MagicMock:
        calls["n"] += 1
        if delay:
            time.sleep(delay)
        return _mock_youtube(vid)

    return factory


async def test_video_cache_hit_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_youtube", _counting_factory(calls))
    v1 = await adapter.video("dQw4w9WgXcQ")
    v2 = await adapter.video("dQw4w9WgXcQ")
    assert calls["n"] == 1
    assert v1.title == v2.title == "Test Title"


async def test_video_cache_expiry_refetches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_youtube", _counting_factory(calls))
    await adapter.video("dQw4w9WgXcQ")
    details, _ = adapter._video_details_cache["dQw4w9WgXcQ"]
    adapter._video_details_cache["dQw4w9WgXcQ"] = (details, time.time() - 1)
    await adapter.video("dQw4w9WgXcQ")
    assert calls["n"] == 2


async def test_cache_hit_returns_independent_unsigned_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/api/video signs by mutating the returned object; the cached canonical
    copy must stay unsigned and later hits must be unaffected."""
    monkeypatch.setattr(adapter, "_make_youtube", lambda vid: _mock_youtube(vid))
    v1 = await adapter.video("dQw4w9WgXcQ")
    v2 = await adapter.video("dQw4w9WgXcQ")
    assert v1 is not v2
    v1.audio_formats[0].url += "&exp=1&sig=" + "ab" * 16  # simulate signing
    assert "sig=" not in v2.audio_formats[0].url
    cached, _ = adapter._video_details_cache["dQw4w9WgXcQ"]
    assert all("sig=" not in af.url for af in cached.audio_formats)


async def test_concurrent_misses_single_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_youtube", _counting_factory(calls, delay=0.05))
    results = await asyncio.gather(*(adapter.video("dQw4w9WgXcQ") for _ in range(5)))
    assert calls["n"] == 1
    # No two callers share an instance (each signs independently downstream).
    assert len({id(r) for r in results}) == 5
    assert adapter._inflight_video == {}


async def test_live_video_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    def live_factory(vid: str) -> MagicMock:
        yt = _mock_youtube(vid)
        yt.vid_info = {
            "videoDetails": {"isLive": True, "title": "L", "author": "A", "channelId": "C"},
            "streamingData": {"hlsManifestUrl": "https://manifest.googlevideo.com/x.m3u8"},
        }
        return yt

    monkeypatch.setattr(adapter, "_make_youtube", live_factory)
    v1 = await adapter.video("livevid12345")
    v2 = await adapter.video("livevid12345")
    assert v1.is_live and v2.is_live
    assert adapter._video_details_cache == {}


async def test_video_ttl_clamped_to_cache_max(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.video_cache_ttl_seconds = 10_000_000
    monkeypatch.setattr(adapter, "get_settings", lambda: settings)
    monkeypatch.setattr(adapter, "_make_youtube", lambda vid: _mock_youtube(vid))
    before = time.time()
    await adapter.video("dQw4w9WgXcQ")
    _, expiry = adapter._video_details_cache["dQw4w9WgXcQ"]
    assert expiry <= before + adapter._CACHE_MAX_TTL + 5.0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_adapter_caches.py -v`
Expected: FAIL — `AttributeError: module 'app.adapters.youtube' has no attribute '_video_details_cache'` (and the conftest fixture fails the whole suite the same way — that's expected until Step 4).

- [ ] **Step 4: Implement**

In `app/adapters/youtube.py`:

(a) Add the import (after the `app.models` import block):

```python
from app.config import get_settings
```

(b) Below the `_inflight_refresh` dict (~line 50), add:

```python
# Cache: video_id -> (VideoDetails, expiry_epoch). Holds the canonical UNSIGNED
# copy — /api/video signs by MUTATING the object it gets, so readers always
# receive model_copy(deep=True), never the cached instance. Live videos are
# never stored (post-fetch discard: live state goes stale fast). The clamp to
# _CACHE_MAX_TTL is for metadata freshness (title/views/format availability
# drift) — the cached proxy paths are unsigned and stable, with no expiry
# coupling to _stream_url_cache.
_video_details_cache: dict[str, tuple[VideoDetails, float]] = {}

# Cache: (query, category, live, limit) -> (hits, expiry_epoch). Read/write
# logic lives in search(); swept by _evict_expired.
_search_cache: dict[tuple[str, str | None, bool, int], tuple[list[SearchHit], float]] = {}

# In-flight video() fetches, keyed by video_id — same single-flight shape as
# _inflight_refresh. Self-cleaning: popped in a finally.
_inflight_video: dict[str, asyncio.Task[VideoDetails]] = {}
```

(c) Replace the body of `video()`:

```python
async def video(video_id: str) -> VideoDetails:
    # Metadata cache hit: deep-copy so per-request signing can't touch the
    # cached canonical (see _video_details_cache comment).
    cached = _video_details_cache.get(video_id)
    if cached and cached[1] > time.time():
        return cached[0].model_copy(deep=True)
    # Single-flight: concurrent misses for the same id share one fetch. The
    # check-and-create is atomic within the event loop (no await between the
    # .get() and the assignment), mirroring _refresh_cache_once.
    task = _inflight_video.get(video_id)
    if task is not None:
        # Joiners copy too — sharing the creator's instance would double-sign.
        return (await task).model_copy(deep=True)
    task = asyncio.create_task(_to_thread_mapped(_fetch_video_cached, video_id))
    _inflight_video[video_id] = task
    try:
        return await task
    finally:
        _inflight_video.pop(video_id, None)
```

(d) Add `_fetch_video_cached` directly below `_fetch_video` (thread-bound section):

```python
def _fetch_video_cached(video_id: str) -> VideoDetails:
    """_fetch_video plus the metadata-cache write. Runs in a to_thread worker
    (construction + stream iteration touch network + Node-cipher work)."""
    details = _fetch_video(video_id)
    if not details.is_live:
        ttl = min(float(get_settings().video_cache_ttl_seconds), _CACHE_MAX_TTL)
        _video_details_cache[video_id] = (details.model_copy(deep=True), time.time() + ttl)
    return details
```

- [ ] **Step 5: Run the new tests, then the full suite**

Run: `uv run pytest tests/unit/test_adapter_caches.py -v`
Expected: all PASS.

Run: `uv run pytest -q`
Expected: PASS. If any existing test fails on cache pollution, the conftest fixture from Step 1 was mis-applied — fix there, not by sprinkling clears in test files. Record baseline pass count before/after.

- [ ] **Step 6: Lint + types**

Run: `uv run ruff check . && uv run mypy app/ --strict`
Expected: clean. (`SearchHit` is already imported in the adapter; `_search_cache`'s annotation needs it.)

- [ ] **Step 7: Commit**

```bash
git add app/adapters/youtube.py tests/conftest.py tests/unit/test_adapter_caches.py
git commit -m "feat(adapter): VideoDetails metadata cache with single-flight and live bypass"
```

---

### Task 3: Search result cache + unified eviction sweep

**Files:**
- Modify: `app/adapters/youtube.py` (`search()` ~line 144, `_evict_expired` ~line 315, new `_collect_and_cache_search` next to `_collect_search_hits` ~line 500)
- Test: `tests/unit/test_adapter_caches.py` (append)

**Interfaces:**
- Consumes: `_search_cache` (created in Task 2), `Settings.search_cache_ttl_seconds` (Task 1), existing `_collect_search_hits`.
- Produces: thread-bound `_collect_and_cache_search(s: Any, limit: int, cache_key: tuple[str, str | None, bool, int]) -> list[SearchHit]`; `_evict_expired` now sweeps all three caches. Public `search(...)` signature unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_adapter_caches.py`:

```python
# ---- search cache ---------------------------------------------------------


def _mock_search_result() -> MagicMock:
    s = MagicMock()
    v = MagicMock()
    v.video_id = "vid00000001"
    v.title = "Hit"
    v.author = "A"
    v.thumbnail_url = "https://i.ytimg.com/vi/vid00000001/hq.jpg"
    v.length = 100
    v.is_live = False
    s.videos = [v]
    s.channels = []
    s.playlists = []
    return s


def _counting_search_factory(calls: dict[str, int]) -> Any:
    def factory(q: str, *, filters: Any = None) -> MagicMock:
        calls["n"] += 1
        return _mock_search_result()

    return factory


async def test_search_cache_hit_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_search", _counting_search_factory(calls))
    r1 = await adapter.search("cache me", limit=5)
    r2 = await adapter.search("cache me", limit=5)
    assert calls["n"] == 1
    assert [h.id for h in r1] == [h.id for h in r2] == ["vid00000001"]


async def test_search_cache_key_includes_params(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_search", _counting_search_factory(calls))
    await adapter.search("q", limit=5)
    await adapter.search("q", limit=10)          # different limit -> miss
    await adapter.search("q", limit=5, live=True)  # different live -> miss
    assert calls["n"] == 3


async def test_search_cache_expiry_refetches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_search", _counting_search_factory(calls))
    await adapter.search("q", limit=5)
    key = ("q", None, False, 5)
    hits, _ = adapter._search_cache[key]
    adapter._search_cache[key] = (hits, time.time() - 1)
    await adapter.search("q", limit=5)
    assert calls["n"] == 2


async def test_search_write_sweeps_all_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """A search-only session must still evict expired entries everywhere —
    _refresh_cache (the old sole sweep site) never runs on this path."""
    monkeypatch.setattr(adapter, "_make_search", _counting_search_factory({"n": 0}))
    stale = time.time() - 10
    adapter._stream_url_cache[("dead", 140)] = ("https://x", stale)
    adapter._video_details_cache["dead"] = (MagicMock(), stale)
    adapter._search_cache[("old", None, False, 20)] = ([], stale)
    await adapter.search("fresh", limit=5)
    assert ("dead", 140) not in adapter._stream_url_cache
    assert "dead" not in adapter._video_details_cache
    assert ("old", None, False, 20) not in adapter._search_cache
    assert ("fresh", None, False, 5) in adapter._search_cache
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_adapter_caches.py -v -k search`
Expected: FAIL — `calls["n"] == 1` assertions fail (no cache; every call fetches) and the sweep test fails (stale entries survive).

- [ ] **Step 3: Implement**

In `app/adapters/youtube.py`:

(a) In `search()`, add the cache check at the top and route collection through the caching wrapper (full new body — signature unchanged):

```python
async def search(
    query: str,
    limit: int = 20,
    *,
    category: str | None = None,
    live: bool = False,
) -> list[SearchHit]:
    cache_key = (query, category, live, limit)
    cached = _search_cache.get(cache_key)
    if cached and cached[1] > time.time():
        return list(cached[0])  # shallow list copy; hits are not mutated downstream
    raw_filters = _build_search_filters(category=category, live=live)
    pytubefix_filters: dict[str, Any] | None = None
    wants_music = False
    if raw_filters is not None:
        wants_music = raw_filters.pop("_music_topic", False)
        pytubefix_filters = raw_filters if raw_filters else None
    s = await _to_thread_mapped(_make_search, query, filters=pytubefix_filters)
    if wants_music:
        # pytubefix's `Search.__init__` doesn't accept an `sp` kwarg; the encoded
        # filter protobuf lives on `s.filter` and is read at request time. Rebuild
        # it with the music-topic field merged in. On encoder failure, leave
        # `s.filter` untouched so the search degrades to type=Video + features.
        _inject_music_topic(s, pytubefix_filters)
    return await _to_thread_mapped(_collect_and_cache_search, s, limit, cache_key)
```

(b) Add `_collect_and_cache_search` directly below `_collect_search_hits`:

```python
def _collect_and_cache_search(
    s: Any, limit: int, cache_key: tuple[str, str | None, bool, int]
) -> list[SearchHit]:
    """_collect_search_hits plus the search-cache write and an eviction sweep.

    Runs in a to_thread worker (hit collection is the network-lazy part).
    The sweep runs HERE because a search-only session never reaches
    _refresh_cache — without it the search cache would grow unbounded.
    """
    hits = _collect_search_hits(s, limit)
    ttl = float(get_settings().search_cache_ttl_seconds)
    _search_cache[cache_key] = (list(hits), time.time() + ttl)
    _evict_expired()
    return hits
```

(c) Replace `_evict_expired` so it sweeps all three dicts:

```python
def _evict_expired(now: float | None = None) -> None:
    """Drop expired entries from all adapter caches.

    Without this the caches grow unbounded over a long-running process.
    Called off the request hot path: after each refresh (stream-URL miss) and
    after each search-cache write. Keys are snapshotted first: writers run in
    asyncio.to_thread workers, so a concurrent writer could otherwise mutate
    a dict mid-iteration.
    """
    cutoff = now if now is not None else time.time()
    caches: tuple[dict[Any, Any], ...] = (
        _stream_url_cache,
        _video_details_cache,
        _search_cache,
    )
    for cache in caches:
        for key in list(cache.keys()):
            entry = cache.get(key)
            if entry is not None and entry[1] <= cutoff:
                cache.pop(key, None)
```

- [ ] **Step 4: Run the new tests, then the full suite**

Run: `uv run pytest tests/unit/test_adapter_caches.py -v`
Expected: all PASS.

Run: `uv run pytest -q`
Expected: PASS vs. Task 2's baseline. Watch `tests/unit/test_music_topic.py` and `tests/unit/test_api_search.py` specifically — if a music-topic test calls `adapter.search` twice with identical args within one test, the second call now short-circuits before `_make_search`/`_inject_music_topic`; fix by varying the query string in that test (comment why), never by weakening the cache.

- [ ] **Step 5: Lint + types**

Run: `uv run ruff check . && uv run mypy app/ --strict`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add app/adapters/youtube.py tests/unit/test_adapter_caches.py
git commit -m "feat(adapter): search result cache; eviction sweep covers all caches"
```

---

### Task 4: `scripts/setup.sh` + README quick-start

**Files:**
- Create: `scripts/setup.sh` (mode 755)
- Modify: `README.md` (Quick start section, lines 13-27)
- Modify: `scripts/dev.sh` (stale error message, line 13)

**Interfaces:**
- Consumes: `.env.example` (ships `API_BEARER_TOKEN=` / `STREAM_SIGNING_KEY=` as blank `KEY=` lines — the in-place fill depends on that shape), `scripts/dev.sh`, `scripts/build.sh`, `hum` console script (pyproject `[project.scripts]`).
- Produces: `./scripts/setup.sh [--secrets-only|--dev|--prod]` — the command the README and Docker path reference.

- [ ] **Step 1: Write the script**

Create `scripts/setup.sh`:

```bash
#!/usr/bin/env bash
# One-command setup: secrets + backend deps + frontend deps.
#
#   ./scripts/setup.sh                 # secrets + uv sync + npm ci
#   ./scripts/setup.sh --secrets-only  # just write .env (the Docker path)
#   ./scripts/setup.sh --dev           # setup, then start dev servers
#   ./scripts/setup.sh --prod          # setup, build frontend, run server
#
# Idempotent: only BLANK `KEY=` values in .env are filled; existing values are
# never touched; a second run is a no-op. Secrets are filled IN PLACE (never
# appended) because .env.example already ships blank `KEY=` lines — appending
# would create duplicate keys whose winner depends on dotenv parse order.
set -euo pipefail
cd "$(dirname "$0")/.."

mode="${1:-}"
case "$mode" in
  ""|--secrets-only|--dev|--prod) ;;
  *) echo "usage: $0 [--secrets-only|--dev|--prod]" >&2; exit 2 ;;
esac

command -v python3 >/dev/null || { echo "python3 not found on PATH" >&2; exit 1; }

# --- secrets ---------------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  echo "created .env from .env.example"
fi

fill_blank_key() {
  # fill_blank_key KEY VALUE — replace a blank `KEY=` line with `KEY=VALUE`.
  # Non-blank values are left untouched. mktemp+mv instead of sed -i for
  # BSD/GNU portability.
  local key="$1" value="$2" tmp
  if grep -q "^${key}=$" .env; then
    tmp="$(mktemp)"
    sed "s|^${key}=\$|${key}=${value}|" .env > "$tmp"
    mv "$tmp" .env
    echo "generated ${key}"
  elif ! grep -q "^${key}=" .env; then
    printf '%s=%s\n' "$key" "$value" >> .env
    echo "generated ${key} (key was absent — appended)"
  fi
}

fill_blank_key API_BEARER_TOKEN "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
fill_blank_key STREAM_SIGNING_KEY "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

if [ "$mode" = "--secrets-only" ]; then
  echo ".env ready."
  exit 0
fi

# --- deps ------------------------------------------------------------------
command -v uv >/dev/null || { echo "uv not found. Install it: https://docs.astral.sh/uv/" >&2; exit 1; }
uv sync --extra dev
npm --prefix frontend ci

case "$mode" in
  --dev)  exec ./scripts/dev.sh ;;
  --prod) ./scripts/build.sh && exec uv run hum ;;
  *)      echo "setup complete — next: ./scripts/dev.sh (dev) or ./scripts/setup.sh --prod" ;;
esac
```

Then: `chmod +x scripts/setup.sh`

- [ ] **Step 2: Verify against the spec's acceptance criteria**

The real `.env` has live values — back it up first, restore after:

```bash
SCRATCH="$(mktemp -d)"   # working dir for before/after comparisons
cp .env .env.orig-backup && rm .env
./scripts/setup.sh --secrets-only
# 1. Both keys non-blank, valid shapes:
grep -Ec "^STREAM_SIGNING_KEY=[0-9a-f]{64}$" .env          # expect: 1
awk -F= '/^API_BEARER_TOKEN=/{print (length($2) >= 16)}' .env  # expect: 1
# 2. No duplicate KEY= lines:
grep -c "^API_BEARER_TOKEN=" .env                           # expect: 1
grep -c "^STREAM_SIGNING_KEY=" .env                         # expect: 1
# 3. Idempotency — second run is a byte-identical no-op:
cp .env "$SCRATCH/env.first"   # SCRATCH from mktemp above
./scripts/setup.sh --secrets-only
cmp .env "$SCRATCH/env.first" && echo IDEMPOTENT         # expect: IDEMPOTENT
# 4. Generated values pass app validation:
API_BEARER_TOKEN="" STREAM_SIGNING_KEY="" uv run --no-sync python -c "
from dotenv import dotenv_values
v = dotenv_values('.env')
from app.config import Settings
Settings(api_bearer_token=v['API_BEARER_TOKEN'], stream_signing_key=v['STREAM_SIGNING_KEY'])
print('VALID')
"                                                            # expect: VALID
# 5. Pre-set values preserved (the restored original must survive a run):
mv .env.orig-backup .env
cp .env "$SCRATCH/env.orig"
./scripts/setup.sh --secrets-only
cmp .env "$SCRATCH/env.orig" && echo PRESERVED           # expect: PRESERVED
```

All five must pass. If `cmp` fails at step 3 or 5, the fill logic is wrong — fix before continuing (do NOT proceed with a clobbering script).

Also run the no-flag path once (deps already present, so it's a fast no-op sync):
`./scripts/setup.sh` — expect "setup complete" and exit 0.

- [ ] **Step 3: Fix the stale dev.sh error message**

In `scripts/dev.sh`, replace line 13:

```bash
  echo "no .venv found — run ./scripts/setup.sh first"
```

- [ ] **Step 4: Rewrite the README quick-start**

Replace the current `## Quick start` section (README lines 13-27) with:

````markdown
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
````

Check the rest of the README for now-contradicting text (the old venv instructions appear only in Quick start; the Frontend/Testing sections already match).

- [ ] **Step 5: Verify README ordering**

Run: `grep -n "setup.sh\|pip install" README.md | head`
Expected: `setup.sh` references appear before the single `pip install` mention (which lives inside the `<details>` footnote).

- [ ] **Step 6: Commit**

```bash
git add scripts/setup.sh scripts/dev.sh README.md
git commit -m "feat(scripts): one-command setup.sh; README leads with Docker + uv paths"
```

Note for the final report: `docker compose up` end-to-end can't be verified in this environment (docker not on PATH) — flag it as maintainer-verify. The compose file itself is unchanged by design.

---

### Task 5: `check.sh fast` mode + staleness-guarded sync

**Files:**
- Modify: `scripts/check.sh`

**Interfaces:**
- Consumes: existing check.sh structure (mode arg parsing, `fail()` helper).
- Produces: `./scripts/check.sh fast`; stamp file `.venv/.sync-stamp`. Full-gate CHECK commands unchanged (only the redundant no-op `uv sync` is skipped; CI is unaffected because CI runs its own steps and never calls check.sh).

- [ ] **Step 1: Implement both changes**

(a) Extend the mode parsing and usage text:

```bash
#   ./scripts/check.sh fast       # inner loop: ruff+mypy+pytest(no cov)+vitest — NOT a pre-push substitute
```

```bash
case "$want" in
  all|backend|frontend|fast) ;;
  *) echo "usage: $0 [all|backend|frontend|fast]" >&2; exit 2 ;;
esac
```

(b) Insert the fast block after the `fail()` definition, before the backend block:

```bash
if [ "$want" = "fast" ]; then
  # Inner-loop mode: assumes a previously-synced .venv (uv errors clearly if
  # it's missing — run ./scripts/setup.sh first). --no-sync is load-bearing:
  # plain `uv run` re-syncs on a stale lockfile, defeating the fast path.
  echo "── fast: ruff ─────────────────────────────────────────"
  uv run --no-sync ruff check . || fail "ruff"
  echo "── fast: mypy --strict ────────────────────────────────"
  uv run --no-sync mypy app/ --strict || fail "mypy"
  echo "── fast: pytest (no coverage) ─────────────────────────"
  uv run --no-sync pytest -q || fail "pytest"
  echo "── fast: vitest ───────────────────────────────────────"
  npm --prefix frontend test || fail "vitest"
  echo "✓ fast checks green — run ./scripts/check.sh before pushing."
  exit 0
fi
```

(c) Replace the unconditional sync block inside the backend section:

```bash
  stamp=".venv/.sync-stamp"
  if [ ! -f "$stamp" ] || [ uv.lock -nt "$stamp" ] || [ pyproject.toml -nt "$stamp" ]; then
    echo "── backend: sync deps (dev extras) ────────────────────"
    uv sync --extra dev || fail "uv sync"
    touch "$stamp"
  else
    echo "── backend: deps unchanged — skipping uv sync ─────────"
  fi
```

Everything else in the file stays byte-identical (the check commands ARE the CI mirror — don't touch them).

- [ ] **Step 2: Verify fast mode**

Run: `./scripts/check.sh fast`
Expected: exits 0; output shows the four fast sections; NO coverage table in the pytest output; `frontend/dist/` mtime unchanged (`ls -ld frontend/dist` before/after — no vite build ran).

Run: `./scripts/check.sh nonsense`
Expected: usage line, exit 2.

- [ ] **Step 3: Verify the staleness guard state machine**

```bash
rm -f .venv/.sync-stamp
./scripts/check.sh backend   # no stamp -> syncs, creates stamp
ls .venv/.sync-stamp          # exists
./scripts/check.sh backend   # stamp fresh -> "skipping uv sync"
touch pyproject.toml
./scripts/check.sh backend   # pyproject newer -> syncs again
```

Expected: sync → skip → sync, all three runs green.

- [ ] **Step 4: Commit**

```bash
git add scripts/check.sh
git commit -m "feat(scripts): check.sh fast mode + staleness-guarded uv sync"
```

---

### Task 6: `dev.sh` reload scoping + final full gate

**Files:**
- Modify: `scripts/dev.sh` (line 21)

**Interfaces:**
- Consumes: everything previous tasks produced (this task ends with the whole-branch gate).

- [ ] **Step 1: Scope uvicorn reload to `app/`**

Replace line 21 of `scripts/dev.sh`:

```bash
uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000 &
```

(Intended side effect, per spec: edits outside `app/` — `.env`, `pyproject.toml`, scripts — no longer trigger backend reload; restart dev.sh for those.)

- [ ] **Step 2: Verify**

Run: `grep -n "reload-dir app" scripts/dev.sh`
Expected: the modified line 21.

Optional live check (needs two terminals, maintainer may prefer to do this): start `./scripts/dev.sh`, `touch frontend/src/App.svelte`, confirm uvicorn does NOT log "Reloading"; `touch app/main.py`, confirm it DOES.

- [ ] **Step 3: Run THE gate**

Run: `./scripts/check.sh`
Expected: "✓ all checks green." — full backend (ruff, mypy --strict, pytest+cov) and frontend (svelte-check, vitest, vite build). This is the whole-branch gate; do not claim done without this output.

- [ ] **Step 4: Commit**

```bash
git add scripts/dev.sh
git commit -m "chore(scripts): scope uvicorn reload to app/"
```

- [ ] **Step 5: Report**

Summarize per CLAUDE.md reporting rules: baseline vs final test counts, commits on `chore/setup-perf-spec`, and the two maintainer-only verifications: (1) `docker compose up` end-to-end (docker unavailable here), (2) the live dev.sh reload check if skipped. NEVER push.
