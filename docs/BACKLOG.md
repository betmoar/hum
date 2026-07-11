# Backlog & residual risk register

Prioritized. Each item has enough context to be picked up cold. P1 = do next,
P3 = nice to have. Nothing here is release-blocking; the release-blocking issues found
in the 2026-07 audit were fixed (see `tests/unit/test_audit_regressions.py`). The
2026-07 backlog sweep cleared all P1/P2 items, leaving only the accepted residual
risks below and P3 notes.

## Residual risks (accepted, not fixed — know they exist)

| Risk | Why accepted |
|---|---|
| Bearer token lives in browser localStorage; any XSS = full compromise. | Single-user LAN app; no third-party scripts. CSP is now shipped (`app/static.py`), reducing blast radius for script-injection XSS, but `style-src 'unsafe-inline'` remains (required by Svelte 5's compiled `element.style.cssText` writes) so style-based exfiltration vectors aren't fully closed. |
| YouTube can invalidate cached CDN URLs early (IP change) → mid-play 403 until the frontend's refetch recovery kicks in. | Mitigated: `/proxy/audio` now evicts the stale `(video_id, itag)` cache entry and retries the resolve once on 403/410 before streaming the error through (`app/proxy/_common.py`). Only a persistent 403 still falls to the frontend recovery dance. |
| `pytubefix` is reverse-engineered; total breakage is a *when*, not *if*. | Contained by invariant 1 + playbook 1. |
| No rate limiting anywhere. | Single trusted user; bearer gate. Do not expose to the internet. |
| Live master-manifest fetches have no single-flight (concurrent pollers may double-fetch during the 2 s cache window). | One listener in practice; harmless duplicate GET. |

## P1

_(None open — cleared in the 2026-07 backlog sweep.)_

## P2

_(None open — cleared in the 2026-07 backlog sweep.)_

## P3

- **`aiohttp` is a transitive dep of pytubefix only.** Dependabot bumps it (see git
  log); nothing imports it directly. No action — just don't be confused by it.
