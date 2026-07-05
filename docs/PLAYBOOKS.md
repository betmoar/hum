# Playbooks

Step-by-step procedures for the recurring judgment calls in this codebase. Written to
be followed literally. Each has: when to use it, the steps, and the trap that catches
people.

---

## 1. pytubefix broke (YouTube changed something)

**Symptoms.** `/api/video` returns 502 `UPSTREAM_FAILURE` or 503 `YOUTUBE_BLOCKED`;
logs show pytubefix exception names; the frontend toasts "Could not load this track."

**Steps.**
1. Confirm it's real, not one dead video:
   `uv run pytest -m integration` (5 tests against live YouTube).
2. Read the error code in the JSON response:
   - `YOUTUBE_BLOCKED` (503) → YouTube is refusing this IP/client (bot detection,
     po_token wall). Not a code bug. Options, in order: wait an hour (blocks are often
     transient); update pytubefix (`uv lock --upgrade-package pytubefix && uv sync`);
     enable pytubefix's po_token/oauth support inside `_make_youtube()` — and ONLY
     there (invariant 1).
   - `UPSTREAM_FAILURE` (502) → pytubefix itself crashed (YouTube changed a page
     shape). Check https://github.com/JuanBindez/pytubefix/issues — someone hit it
     first. Upgrade; if no release yet, pin to their fix branch temporarily and leave
     a dated TODO.
3. All changes go in `app/adapters/youtube.py`. If you feel the urge to touch another
   file, you're about to break invariant 1 — stop.
4. `./scripts/check.sh backend`, then `uv run pytest -m integration` again.

**Trap.** Do NOT catch broad exceptions in routes to "fix" a 500. The adapter maps
pytubefix errors to `YouTubeError` (`_map_pytubefix_error`); the global handlers in
`app/main.py` turn those into JSON. If a new pytubefix exception leaks as a 500, add
it to the mapping in the adapter, not a try/except in a route.

---

## 2. Adding an API endpoint

1. Route module in `app/api/`, one file per resource. Copy `app/api/channel.py` as the
   skeleton.
2. Auth: JSON endpoints get `dependencies=[Depends(require_bearer)]`. Anything a media
   element must fetch (can't send headers) gets a signed URL instead — see playbook 3.
3. Validate path params with a constrained type (`VideoID` in `app/models.py` is the
   template — length + regex at the model layer).
4. Response shape: Pydantic model in `app/models.py`, then mirror it by hand in
   `frontend/src/lib/types.ts` (same field names, snake_case).
5. Never call pytubefix or httpx directly — go through `app.adapters.youtube` /
   `app.adapters.upstream_http`. Let `YouTubeError` propagate; the global handlers
   format it.
6. If the route adds a new top-level path prefix (not `/api/` or `/proxy/`), add it to
   `_SPA_RESERVED_PREFIXES` in `app/static.py`, or the SPA fallback will serve
   index.html instead of your 404s.
7. Run `./scripts/check.sh`. `test_invariant_3_every_route_is_authed_or_signed` will
   fail if you forgot auth — that's it working. A deliberately public route goes into
   `_PUBLIC_PATHS` in `tests/unit/test_invariants.py` with a comment saying why.

**Trap.** Returning `JSONResponse` directly from a route bypasses `response_model`
validation. Fine for error paths; never do it for success payloads.

---

## 3. Adding a new signed-URL type

Copy the live-segment pair in `app/auth.py` (`sign_live_segment_url` /
`verify_live_segment_signature`) as the template.

1. **Unique payload prefix.** The signature message must start with a literal that no
   other scheme uses (`live-segment|`, `live-manifest|`). This prevents a signature
   minted for one endpoint from verifying on another.
2. **Sign everything the endpoint trusts.** If the URL carries a parameter the handler
   acts on (an upstream URL, an itag), it goes inside the signed message. The `u`
   param of live segments is the worked example — unsigned, it would be an open proxy.
3. **Expiry required.** `exp` in the payload, checked before the digest.
4. Verify with `secrets.compare_digest`, truncate digests to 32 hex chars (128 bits),
   raise `SignatureError` with 410 (expired) / 403 (invalid).
5. Mint only in `/api/*` handlers (bearer-gated); verify in the serving route.
6. If the signed URL ends up on a `Track` in the frontend, strip it in
   `store.svelte.ts` `#flush()` AND the rehydrate map — persisted signed URLs are
   stale by definition and Safari will try to play them (this was a real bug).
7. Tests: expired → 410, tampered sig → 403, tampered params → 403, happy path.
   `tests/unit/test_auth.py` has the pattern.

---

## 4. Changing the stream URL cache / single-flight logic

The cache in `app/adapters/youtube.py` is the highest-risk hot path. Rules:

- Keys: `(video_id, itag)` for VOD, `("live", video_id)` for live. Values:
  `(url, expiry_epoch)`.
- Writers run in `asyncio.to_thread` worker threads; readers on the event loop. Only
  single dict operations (get/set/pop) are safe — they're GIL-atomic. No
  read-modify-write sequences without rethinking the whole design.
- `_refresh_cache_once` relies on there being NO `await` between checking
  `_inflight_refresh` and storing the new task. Adding one reintroduces the duplicate
  concurrent-fetch bug it exists to prevent.
- Expiry is `min(YouTube's expire=, now + _CACHE_MAX_TTL)`. Raising `_CACHE_MAX_TTL`
  above 1 h trades fewer pytubefix calls for more mid-play 403s (YouTube invalidates
  URLs early on IP change).
- After changing anything here run `tests/unit/test_youtube_adapter.py` — it encodes
  the stale-itag-eviction and single-flight semantics.

---

## 5. Frontend: touching Player.svelte or the store

- One `<audio>` element, owned by `Player.svelte`, mounted in `App.svelte` outside the
  router. Never create a second one (the store's `switchQuality` queries
  `document.querySelector('audio')` — a second element breaks it silently).
- Any imperative `play()` call goes through `safePlay()` — bare `el.play()` produces
  unhandled rejections under autoplay policy.
- Live tracks: hls.js owns error recovery. `handleError` deliberately returns early
  for `isLive` — don't "add" recovery there.
- New persisted field on `Track`? If it's a signed URL, strip on persist + rehydrate
  (see `#flush`). If not, confirm it serializes (no functions/DOM refs).
- The store is a singleton with `$effect.root` — tests import a fresh copy via
  `vi.resetModules()` + dynamic import. Follow the pattern in
  `frontend/tests/unit/store.test.ts`.

---

## 6. Dependency bumps

- Backend: `uv lock --upgrade-package <name> && uv sync --extra dev`, then
  `./scripts/check.sh backend`. pytubefix bumps additionally warrant
  `uv run pytest -m integration` because its breakage is behavioral, not typed.
- Frontend: `npm update <name>` in `frontend/`, then `./scripts/check.sh frontend`.
- hls.js is loaded via dynamic import and its config
  (`liveSyncDuration`, retry policies in `Player.svelte`) is tuned against YouTube's
  ~5 s live segments — a major-version bump needs a manual live-radio listen test.

---

## 7. Release

Tag `vX.Y.Z` on main → `.github/workflows/release.yml` re-runs the full gate, packages
`frontend/dist`, extracts the CHANGELOG section for that version, publishes a GitHub
Release. Keep `CHANGELOG.md` in Keep-a-Changelog format — the awk extraction in the
workflow depends on `## [X.Y.Z]` headings.
