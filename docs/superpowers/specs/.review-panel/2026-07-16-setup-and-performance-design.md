# Panel run — 2026-07-16-setup-and-performance-design.md  (2026-07-16 23:38)
- **artifact:** docs/superpowers/specs/2026-07-16-setup-and-performance-design.md     **reviewer:** glm-review-design     **N:** 3
- **lenses:** A ambiguity · B contradictions/feasibility · C testability
- **per-lens:** A → 17 findings · B → 13 · C → 13
- **buckets:** must-resolve 5 · should-clarify 3 (asked) · consider 8 · dropped <50: ~27 (mostly C's per-line acceptance-criterion demands folded into the plan phase, plus dedups)
- **asked:** 3 should-clarify → answers in the artifact's Clarifications section
- **verdict:** Section 2 (caches) sound with rationale fixes; Section 1's Docker path was infeasible as written (USER hum + host-side env_file) and was redesigned to host-side secret gen; Section 3 needed precision on "byte-identical" and fast-mode invocation.

## Findings
### must-resolve
- [95] Docker entrypoint can't write /app/.env as USER hum, and compose `env_file: .env` resolves host-side before container start — entrypoint-generated .env can't feed it (lens B, corroborated by lens A f1). → Resolved: redesign to host-side secret generation; drop the entrypoint.
- [85] `cp .env.example .env` + append ⇒ duplicate keys (`API_BEARER_TOKEN=` blank line survives); python-dotenv first-wins would read the blank (lens A f2). → Fix: replace blank values in place, never append duplicates.
- [80] No single-flight on the new metadata cache — concurrent misses each fire pytubefix, unlike `_inflight_refresh` (lens A f4). → Resolved: reuse the in-flight pattern (user confirmed).
- [80] Search-only traffic never triggers `_evict_expired` (it only runs in `_refresh_cache`) — search cache grows unbounded in a search-only session (lens A f3, corroborated lens B). → Fix: sweep on search-cache write too.
- [75] "check.sh full-run semantics stay byte-identical" contradicts the staleness-guarded uv sync (lens A f6). Also CI never calls check.sh at all (.github/workflows/ci.yml has its own steps — verified) so the "fresh runner → no stamp" rationale is wrong. → Fix: correct both statements.

### should-clarify  (→ asked)
- [70] Docker .env redesign direction → **A: Host-side gen** — setup.sh generates .env on host; compose keeps `env_file:`; no entrypoint secret magic.
- [65] Single-flight for metadata cache → **A: Yes** — reuse the keyed in-flight task pattern.
- [62] Live videos pay full pytubefix cost every call (bypass is necessarily post-fetch) → **A: Accept full cost**; spec states post-fetch discard explicitly.

### consider
- [70→folded] TTL-clamp rationale wrong: cached VideoDetails holds unsigned, stable proxy paths — no expiry coupling to stream URLs. Real reason is metadata freshness (lens A f7 + lens B). Fix rationale in spec.
- [70→folded] Live-bypass rationale wrong ("manifest URLs churn" — cached object holds a stable relative path). Real reason: live state goes stale (lens A f11 + lens B).
- [65→folded] fast-mode invocation form unspecified: bare tools need an activated venv; `uv run` re-syncs on stale lock (lens A f16 + lens B). Fix: use `uv run --no-sync`.
- [60→folded] "missing" secret undefined in entrypoint (lens A f5) — mooted by host-side redesign, but setup.sh defines blank-or-absent = missing.
- [55] `model_copy(deep=True)` is a departure from the pure single-dict-op pattern, not "the exact pattern" — call it a deliberate bounded departure (lens B).
- [55] `--prod` invocation undefined (lens A f8) — spec now names the exact commands.
- [55] `fast` arg parsing rule vs existing modes (lens A f10) — mutually exclusive, stated.
- [50] `--reload-dir app` side effects: non-app file edits no longer reload (lens A f17 + lens B) — noted as intended.

Dropped (<50, examples): negative caching for failures (accept default re-fetch, now stated), limit-key cache-miss note, README grep-test, .env gitignore invariant test, container-level compose tests (single-user LAN app; manual verify), dev.sh `npm install` message staleness (touched anyway).

Lens C's per-requirement acceptance criteria (setup.sh idempotency test, stamp-file state machine, fast-mode contract) are real but belong in the implementation plan's test steps — carried forward there rather than bloating the spec; the spec now names the key ones.
