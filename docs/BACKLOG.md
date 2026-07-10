# Backlog & residual risk register

Prioritized. Each item has enough context to be picked up cold. P1 = do next,
P3 = nice to have. Nothing here is release-blocking; the release-blocking issues found
in the 2026-07 audit were fixed (see `tests/unit/test_audit_regressions.py`).

## Residual risks (accepted, not fixed — know they exist)

| Risk | Why accepted |
|---|---|
| Bearer token lives in browser localStorage; any XSS = full compromise. | Single-user LAN app; no third-party scripts. CSP is now shipped (`app/static.py`), reducing blast radius for script-injection XSS, but `style-src 'unsafe-inline'` remains (required by Svelte 5's compiled `element.style.cssText` writes) so style-based exfiltration vectors aren't fully closed. |
| YouTube can invalidate cached CDN URLs early (IP change) → mid-play 403 until the frontend's refetch recovery kicks in. | Recovery works; backend-side retry-on-403 adds complexity for a rare event. |
| `pytubefix` is reverse-engineered; total breakage is a *when*, not *if*. | Contained by invariant 1 + playbook 1. |
| No rate limiting anywhere. | Single trusted user; bearer gate. Do not expose to the internet. |
| Live master-manifest fetches have no single-flight (concurrent pollers may double-fetch during the 2 s cache window). | One listener in practice; harmless duplicate GET. |

## P1

- **`fetch_range` can buffer an entire file.** `app/adapters/upstream_http.py:
  fetch_range` accepts a 200 (full-body) response when the upstream ignores `Range`,
  which `resp.content`-buffers the whole media file in RAM. Reject 200 responses
  larger than ~2× the requested window (check `Content-Length` before reading), or
  stream-and-truncate. Today googlevideo honors ranges, so this is latent.

## P2

- **Backend evicts stale VOD cache on upstream 403.** When `/proxy/audio` gets a 403
  from YouTube, pop the `(video_id, itag)` cache entry and retry the resolve once
  before streaming the 403 through. Removes the only case where a user-visible error
  requires the frontend recovery dance. Keep it bounded: one retry, only on 403/410.
- **`test.sh`-style coverage runner is gone; add coverage to check.sh.**
  `uv run pytest --cov=app` needs `pytest-cov` in dev extras. Gate nothing on it yet;
  just make the number visible.
- **Frontend `switchQuality` DOM reach-in.** `store.svelte.ts` queries
  `document.querySelector('audio')` and attaches a one-shot `loadedmetadata` listener
  that leaks if the event never fires. Route it through the `playerControls` handle
  instead (it already exposes imperative controls; add `getElement()` or a
  `restoreAt(pos)` method).
- **Queue keying churn.** `Queue.svelte` keys `{#each}` by `videoId + ':' + i`, so
  reorder/remove rebuilds shifted rows. Give `Track` a stable per-insertion `queueId`
  (crypto.randomUUID() at enqueue) and key by that. Touches `store.enqueue`/`playNext`
  and persistence (strip nothing — it's inert).
- **Search input debounce banks partial queries into recents.** Split
  `onsubmit`-with-recents from debounced-preview-search in `Search.svelte` so only
  Enter/explicit submits call `withRecent`.

## P3

- **Migrate `migrateLegacy.ts` tests.** The legacy-localStorage migration has no test;
  it's one bad JSON.parse away from wiping a queue. Test: idempotency, new-key-wins,
  malformed legacy data.
- **Router tests.** `routes.svelte.ts` `/video/:id` regex and fallback are untested.
- **Structured logs for the 3am case.** `hum.access` logs path + status; add the error
  code (`YOUTUBE_BLOCKED` etc.) to the log line on 5xx so `docker logs | grep` tells
  the story without a debugger.
- **README badge + CHANGELOG compare links still point at `betmoar/streamtube`.**
  Repo is `betmoar/hum`. Cosmetic; fix when touching docs. (Badge fixed in audit if
  you're reading this after 2026-07; links in CHANGELOG footer remain.)
- **`aiohttp` is a transitive dep of pytubefix only.** Dependabot bumps it (see git
  log); nothing imports it directly. No action — just don't be confused by it.
