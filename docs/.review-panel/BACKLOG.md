# Panel run — implementation vs docs/BACKLOG.md + docs/PLAYBOOKS.md  (2026-07-11)

- **artifact:** docs/BACKLOG.md (impl under review: branch `chore/backlog-sweep`, 10d82ef..2a93af0, 14 commits)     **reviewer:** glm-review-implementation     **N:** 3
- **lenses:** A ambiguity & completeness · B contradictions & feasibility · C testability
- **per-lens:** A → 13 findings · B → 10 · C → 6 (tokens: not reported by GLM agents — omitted)
- **buckets:** must-resolve 1 · should-clarify 0 · consider 2 · dropped <50: ~12
- **asked:** 0 (should-clarify empty → no questions)
- **verdict:** Spec implementation is faithful — no contradictions vs spec/playbooks/CLAUDE.md invariants (B confirmed all 3 invariants intact, single httpx client, queueId frontend-only, eviction single dict.pop). One must-resolve: CSP script-src hash is load-bearing but has no regression test (stub fixture hides drift). Two consider-tier consistency nits. Synthesis done by the strong main model, scoring against the actual code.

## Findings

### must-resolve
- **[80] CSP `script-src` sha256 hash has no failing-on-regression test** (lenses A2+C1+B1 — consensus). `app/static.py:46` hardcodes `'sha256-J03Yqg7SM1LzbD5cOpeyfBlUptzg3Vs99ztMW+Yavgs='`; the comment at `app/static.py:22-33` itself warns a stale hash "fails silently." The test fixture `tests/unit/test_static.py:13-19` writes a STUB `index.html` with no inline `<script>`, so no test recomputes the hash from the real `frontend/dist/index.html` and compares it to `_CSP`. If the theme-bootstrap script in `frontend/index.html:16-26` changes and the hash isn't recomputed, every test stays green while the CSP silently disables the bootstrap (degrades to the 'glass' theme, not a white-screen). Fix: a test that reads `frontend/dist/index.html`, extracts the inline `<script>`, computes sha256, asserts that digest is present in `_CSP`. (Verified independently by the main model: hash currently matches the built dist exactly.)

### consider
- **[58] HLS route error-body shape diverges by upstream exception type** (lens A5/A7). `app/api/hls.py:65-68` local catch only handles `UpstreamStatusError`; the same branch's `fetch_range` rewrite can raise `UpstreamRangeError`/`UpstreamHostError`, which bypass the local `_error` and hit the global handler. No bare 500 (B confirmed global handler maps both to 502 JSON), but the HLS error JSON body differs by exception type and no test covers it. Behavior correct; consistency/observability nit.
- **[55] Proxy `HTTPException` raises don't carry `code=` in the access log** (lens A6). `app/proxy/_common.py:92` signature failure and `app/proxy/thumbnail.py:38,53` log a 403 with no `code=` suffix — the headline `docker logs | grep code=` goal partially misses proxy routes. Real gap, modest stakes (single-user, signature failures are rare and self-evident in the path).

### dropped (<50, not acted on)
- B1–B10 confirmations (invariants intact, single httpx client, queueId frontend-only/no backend mirror, eviction single dict.pop GIL-safe, hum→main()→PORT chain holds, error_code no double-write) — not findings.
- C "no test": docker-port / coverage-check-sh / changelog-links — shell/infra/docs, untestable at this layer by design.
- A3 connect-src/hls.js-worker speculation; A8 coverage-number-undefined; A9 pre-existing-queue migration; A11 EXPOSE-8000-as-hint; A12 DEBUG-true PID-1; B7 restoreAt "relocated not eliminated" (bounded by single-`<audio>` invariant); A13 stale changelog spec text (branch correctly removed it).
