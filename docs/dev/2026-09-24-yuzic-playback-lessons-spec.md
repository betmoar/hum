# Spec — playback lessons from Yuzic

Status: draft, awaiting Gate A. Source: comparison with yuzicapp/yuzic @ e21db61
(`docs/architecture.md` §2, §3, §5, §11).

## Goal

Make Hum remember what was playing, give it a real "previous", centralise
per-content-kind behaviour, tell "Hum server unreachable" apart from "YouTube
failed", expose position to OS media controls, record untested tuning
constants, and (if YouTube supplies the data) attenuate loud tracks.

## Requirements

### R1 — Resume across reloads
- R1.1 `player.current` is persisted (key `hum.current`) with the same
  stripping rules as the queue: `audioUrl: ''`, `hlsUrl`, `liveStreamUrl`,
  `_formats` removed. The strip logic moves into ONE helper
  (`stripSignedUrls(t)`) used by the queue flush, the queue rehydrate, and the
  current-track flush/rehydrate — so the "strip in two places" coupling in
  CLAUDE.md collapses to one place.
- R1.2 On load, a persisted current track is restored **paused**
  (`isPlaying: false`); the `<audio>` element must not autoplay a restored
  track. Pressing play starts it at the restored position.
- R1.3 Per-video resume bookmarks: `hum.bookmarks` =
  `Record<videoId, { pos: number; at: number }>` (seconds, epoch ms).
  Written (throttled, ≤ 1 write / 5 s, plus on `pause` and `pagehide`) only
  when the track is VOD **and** `durationSeconds >= 600`. Cleared for a video
  when playback passes `duration − 30 s` or `ended` fires. Capped at 200
  entries, oldest `at` evicted.
- R1.4 When any VOD track with a bookmark starts (restore, playNow, or
  advance), playback seeks to the bookmark once metadata loads. Tracks under
  600 s always start at 0 (except the R1.2 restored current track, which
  resumes at its persisted position regardless of length).
- R1.5 Live tracks are never bookmarked and always start at the live edge.

### R2 — History and a real "previous"
- R2.1 `store.history: Track[]` (most recent last), capped at 50, persisted
  under `hum.history` with signed URLs stripped (via R1.1 helper).
- R2.2 Every transition that replaces a non-null `current` with a different
  track (`next()`, `playNow()`) pushes the outgoing track onto `history`.
  `repeat: 'one'` replays and `repeat: 'all'` wrap do not push duplicates of
  the replayed track.
- R2.3 `store.previous()`: if position > 3 s **or** history is empty →
  restart current (today's behaviour). Otherwise pop history into `current`
  and put the old current at the FRONT of `queue`. The 3 s threshold matches
  the common player convention.
- R2.4 Wiring: Player prev button, NowPlaying prev button, mediaSession
  `previoustrack`, and the App keyboard handler (if it has a restart binding)
  call `previous()`. Button labels change from "Restart track" to
  "Previous track".
- R2.5 `store.queue` keeps its meaning (upcoming tracks), so Queue page,
  badges and App consumers are unchanged. Chosen over Yuzic's
  `queue + currentIndex` model because every existing consumer treats
  `queue` as "upcoming", and shuffle-by-random-pick has no clean index form.
  Queue page gains no history UI (non-goal).

### R3 — Content-kind behaviour table
- R3.1 New `frontend/src/lib/contentKind.ts`: `type ContentKind = 'vod' | 'live'`,
  `kindOf(t: Track | null): ContentKind | null`, and a table with
  `hasDuration`, `isSeekable`, `isBookmarkable`, `isAirplayRoutable`,
  `usesHls` (live pipeline), plus accessor functions of those names taking a
  track.
- R3.2 Every `isLive` read in `Player.svelte`, `NowPlaying.svelte` and
  `store.svelte.ts` that decides *behaviour* goes through these accessors.
  Reads that construct data (`#buildTrack`) or render the LIVE pill stay as-is.
- R3.3 `Track.isLive` stays the persisted field (no storage migration).

### R4 — Hum-unreachable vs upstream failure
- R4.1 `api.ts`: a `fetch` rejection (network error, not an HTTP status) throws
  `ApiError(0, 'hum server unreachable')`. Status 0 is reserved for this.
- R4.2 `Player.handleError` / rehydrate effects / `#fetchTrack`: on status 0,
  show sticky toast `"Can't reach Hum server."` with a Retry action, and do
  **not** consume the per-video recovery slot (`recoveredVideoIds`) or the
  codec-fallback slot.
- R4.3 Media-element errors can't carry a status; before starting the
  codec/refetch ladder, `handleError` calls `api.health()` (new wrapper on the
  existing public health route — verify path at plan time). If that fails with
  status 0 → R4.2 path; otherwise existing ladder unchanged.
- R4.4 Other toasts unchanged: YouTube-side failures keep "Stream failed. Try
  again?" / "Could not load this track."

### R5 — Media Session position + seek
- R5.1 For VOD tracks, call `navigator.mediaSession.setPositionState({ duration,
  position, playbackRate })` on `loadedmetadata`, `seeked`, `play`, `pause`,
  `ratechange`; guard for missing API and non-finite duration.
- R5.2 Register `seekto`, `seekbackward` (default 10 s), `seekforward`
  (default 10 s) for VOD; set them to `null` for live. All wrapped in
  try/catch (unsupported actions throw).
- R5.3 For live, clear position state (`setPositionState()` with no args)
  where supported.

### R6 — Reasoned-not-measured constants
- R6.1 `docs/ARCHITECTURE.md` gains a section "Tuning constants (reasoned,
  not measured)" listing at least: `_CACHE_MAX_TTL`, the live-manifest cache
  window, hls.js `liveSyncDuration`/`liveMaxLatencyDuration`/retry policies,
  `PERSIST_DEBOUNCE_MS`, and the new R1/R2/R7 constants — value, location,
  what it decides. Values are read from the code at plan time, not typed from
  memory.

### R7 — Loudness attenuation (data-dependent)

> **Dropped (2026-09-24):** not shipped. 0.2.0 replaced pytubefix with yt-dlp, which does not expose `loudnessDb`. Kept here as a record.

- R7.1 Backend: `VideoDetails.loudness_db: float | None = None`, read in
  `app/adapters/youtube.py` from `vid_info["playerConfig"]["audioConfig"]["loudnessDb"]`
  with every level `.get()`-guarded and non-numeric → `None`. Mirrored in
  `types.ts` and carried on `Track.loudnessDb` (persisted; not a URL).
- R7.2 Frontend: effective element volume =
  `userVolume × gain`, `gain = loudnessDb > 0 ? 10^(−loudnessDb/20) : 1`
  (attenuate only — never boost, never clip). Done via `el.volume`, **not**
  Web Audio, because routing through `createMediaElementSource` risks
  breaking Safari native-HLS and AirPlay routing. On iOS `el.volume` is
  read-only; attenuation is a no-op there (accepted).
- R7.3 Setting "Normalize loudness" (`hum.normalize`, default on) in Settings.
- R7.4 **Unverified premise:** this sandbox cannot reach YouTube (proxy 403),
  so the field's presence and sign convention are unconfirmed. An integration
  test (`-m integration`) asserts `loudness_db` is a float for a known music
  video; until it passes on your machine, R7 is inert when the field is absent.

## Non-goals
- Listening log / "interruption is not rejection" (Yuzic §11) — no play log
  exists to protect. Revisit if history-based features land.
- History UI on the Queue page; cross-device sync; Web Audio graph; boosting
  quiet tracks; any change to signing or proxy routes.

## Interfaces
- `store.previous(): void`, `store.history: Track[]`.
- `stripSignedUrls(t: Track): Track` (exported from store module for tests).
- `lib/bookmarks.ts`: `getBookmark(id)`, `saveBookmark(id, pos, dur)`,
  `clearBookmark(id)` — pure localStorage wrapper, try/catch everywhere.
- `lib/contentKind.ts` as R3.1.
- `api.health(): Promise<void>`; `ApiError.status === 0` ⇒ Hum unreachable.
- `VideoDetails.loudness_db` (py) ⇄ `loudness_db?: number | null` (ts).

## Invariants touched
- Invariant 3 / signed-URL persistence: strengthened (single strip helper).
- `models.py` ⇄ `types.ts` coupling: R7.1 updates both.
- No new routes; no pytubefix import outside the adapter.

## Testing
- Vitest: store (history push/pop, previous threshold, repeat interplay,
  persistence strips URLs for current+history, restored-current is paused),
  bookmarks (threshold, clear near end, cap/eviction), contentKind table,
  api (fetch reject → status 0), Player (mediaSession handlers + position
  state with stubbed API; unreachable toast doesn't consume recovery slot;
  volume gain applied).
- Pytest: `loudness_db` parsed / absent / garbage → None; integration test
  for real presence (opt-in).
- Gate: `./scripts/check.sh` green; baseline counts recorded before the first
  edit.

## Success criteria
Reload mid-track → same track shown paused at same position; prev within 3 s
goes to the prior track; lock-screen shows a scrubbable bar for VOD; killing
the Hum server mid-play shows "Can't reach Hum server." not "Stream failed";
`check.sh` green.
