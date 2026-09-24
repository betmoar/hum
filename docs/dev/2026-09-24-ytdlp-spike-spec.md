# Spike spec: yt-dlp vs pytubefix backend

Status: approved (Gate A, 2026-09-24). Sizing M (one subsystem: the YouTube adapter; 3 tasks).

## Question the spike answers

Can yt-dlp replace pytubefix for Hum's two hot paths, `video()` and `search()`?
The bar is equal or better reliability and acceptable latency. The answer comes
from numbers measured on the user's machine; this sandbox gets a 403 from
YouTube, so it cannot measure anything.

## Decision criteria (fixed now, before any numbers exist)

Switch to yt-dlp only if, on the benchmark set below, all of these hold:

| # | Metric | Threshold |
|---|---|---|
| D1 | Cold `video()` p50 (both caches empty) | ≤ 2.5 s **and** ≤ 2× pytubefix p50 |
| D2 | Cold `video()` p95 | ≤ 5 s |
| D3 | `search()` p50 | ≤ pytubefix p50 × 1.3 |
| D4 | Failure rate across the whole set | ≤ pytubefix's |
| D5 | Format parity | itag 140 **or** 251 present for every playable VOD; live yields a manifest |
| D6 | Loudness | Not a threshold. yt-dlp doesn't expose `loudnessDb` (grep of yt-dlp 2026.08.19 finds nothing), so the report records whether it can be recovered. The user decides whether losing it is acceptable. |

If D1–D5 pass, the follow-up is a separate spec: migrate channel and playlist,
delete pytubefix, add a yt-dlp invariant. If any of D1–D5 fails, the spike
branch is closed and the report is kept in `docs/`.

## Scope

- **R1 — Backend setting.** `Settings.yt_backend: Literal["pytubefix", "ytdlp"] = "pytubefix"`
  (env `YT_BACKEND`). Default behaviour is unchanged.
- **R2 — yt-dlp `video()`.** New module `app/adapters/youtube_ytdlp.py`, the only
  file that imports `yt_dlp` (spike-scoped rule, enforced by a new test in
  `test_invariants.py`). Its `fetch_video(video_id) -> VideoDetails` produces the
  same shape as today:
  - VOD: audio and video formats → the same signed proxy paths (`_proxy_path_for`).
    It writes `_stream_url_cache[(video_id, itag)] = (url, expiry)` with the same
    `expire=` parsing and `_CACHE_MAX_TTL` clamp, so `/proxy/audio` plays
    unchanged.
  - Live (`live_status == "is_live"`): the upstream HLS master URL goes through
    the existing live path. The client still gets `/api/live/{id}/manifest.m3u8`,
    never a raw URL (invariant 3).
  - `loudness_db = None` (see D6).
  - Options: `quiet`, `skip_download`, `noplaylist`, no cookies. The JS runtime
    is left at yt-dlp's default (deno).
- **R3 — yt-dlp `search()`.** It uses `https://www.youtube.com/results?search_query=…&sp=…`
  with `extract_flat="in_playlist"`, returning `SearchHit[]` in the same shape.
  The `sp` parameter is built by the adapter's existing encoder output, which
  is lifted into a pytubefix-free helper so both backends share it. Filters
  covered: none, music topic, live.
- **R4 — Dispatch.** `youtube.video()` and `youtube.search()` pick the backend
  from R1 **inside** the existing cache and single-flight wrappers, so the
  caching, refresh and error behaviour around them is identical. `channel()`,
  `playlist()` and `resolve_live_master_url()` stay on pytubefix.
- **R5 — Error mapping.** `yt_dlp.utils.DownloadError` / `ExtractorError` map to
  the existing codes by message class:
  - "Sign in to confirm", "bot", "age", "PO Token" → 503 `YOUTUBE_BLOCKED`
  - "Video unavailable", "Private video", "removed" → 404 `VIDEO_UNAVAILABLE`
  - anything else → 502 `UPSTREAM_FAILURE`

  `app/main.py` handlers stay unchanged, so there are never bare 500s.
- **R6 — deno check.** With `yt_backend="ytdlp"`, startup checks
  `shutil.which("deno")`. If it's missing, the app logs one ERROR naming the
  requirement and link, and keeps serving: YouTube calls then fail through R5.
  It does not crash, because a missing optional tool shouldn't take the app down.
- **R7 — Benchmark.** `scripts/bench_yt_backends.py` (uses the network,
  never run in CI):
  - Input: a fixed list in `scripts/bench_yt_set.json` — 10 music VODs, 3 VODs
    of an hour or more, 2 live (current at run time; editable), 1 age-restricted,
    1 removed/private, and 6 queries (2 plain, 2 music, 2 live).
  - For each backend it clears the adapter caches, runs every item cold, then
    once warm.
  - It records per item: wall time, success/error code, audio itags, whether
    `loudness_db` is set, and field-level differences between the two backends
    for the same item.
  - Output: a markdown report (p50/p95 per path, failure table, parity diffs,
    D1–D6 pass/fail) at `docs/dev/ytdlp-spike-report.md`.
  - `--capture` also saves raw yt-dlp info dicts into `tests/fixtures/ytdlp/`,
    so the unit tests run against real shapes.
- **R8 — Tests.**
  - Unit tests, offline, with `YoutubeDL.extract_info` mocked: VOD mapping,
    live mapping, search mapping for each filter, the R5 error table,
    cache-write parity, dispatch by setting, and the deno warning.
  - The fixtures start as hand-written dicts that follow yt-dlp's documented
    fields. They are replaced by `--capture` output after the first real run.
    Until then they're **unverified against real YouTube**.
  - Integration (`-m integration`, opt-in): the same 5 live tests as today, run
    with `yt_backend="ytdlp"`.

## Non-goals

- Removing pytubefix.
- Migrating channel and playlist.
- Changing the default backend.
- Adding deno to Docker or production (a README note only).
- Recovering loudness under yt-dlp: the spike only reports whether it's
  feasible.
- Adapting cookies or PO-token plugins.

## Plan (tasks, each test-first)

1. **yt-dlp adapter + invariant** (R2, R3, R5)
   - New module plus its unit tests.
   - `sp` encoder lifted into a shared helper; existing search tests stay green.
   - New invariant test: `yt_dlp` is imported only in `youtube_ytdlp.py`.
2. **Dispatch + setting + deno check** (R1, R4, R6)
   - Tests: the default path is untouched (existing suite unchanged), and
     `ytdlp` routes to the new module.
   - The integration tests are parametrised by backend.
3. **Benchmark + capture + docs** (R7)
   - Script, set file, and report template.
   - README/PLAYBOOKS note on how to run it, plus the deno requirement.

Gate: `./scripts/check.sh` green after each task; the pytest baseline is
recorded first.

## Assumptions

- A1: yt-dlp is added as a normal dependency (in `pyproject` / `uv.lock`), not
  shelled out to a system binary. The Python API is faster (no process start),
  has structured errors, and is testable. The system requirement becomes
  `deno`, not yt-dlp.
- A2: the spike lives on a new branch off `main`, not PR #12's branch. This
  needs the user's OK: the session is pinned to
  `betmoar/eager-ramanujan-3nxmyl`.
- A3: the thresholds in D1–D5 are the user's to change now. After the numbers
  arrive they don't move.
- A4: only the user's machine can run R7. The sandbox deliverable is code plus
  offline tests; the measurement is the user's.
