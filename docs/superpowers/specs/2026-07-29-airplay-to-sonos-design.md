# AirPlay from Safari to Sonos — design

Date: 2026-07-29
Status: draft, pending maintainer approval

## Problem

Playing Hum through a Sonos speaker today requires macOS System Settings → Sound
→ Output, which routes **all** system audio (notification dings included) and
adds latency that disagrees with the scrubber. What's wanted is a per-element
route: an AirPlay button in Hum's own transport that sends only Hum's audio to
the speaker.

Safari exposes this, but Hum's `<audio>` element has no `controls` attribute
(`frontend/src/components/Player.svelte:416-426`) — the app draws its own
transport — so Safari never renders the native media bar where its free AirPlay
button lives. The picker has to be driven from our own UI.

## What AirPlay actually does here (constrains everything below)

AirPlay to a **speaker** is a source-encoded push, not a URL handoff: the Mac
decodes our stream, re-encodes to ALAC (capped 16-bit/44.1 kHz), and streams to
the Sonos itself. The speaker never fetches our URL. This is the opposite of
Chromecast, and different from AirPlay video-to-AppleTV, which *is* a URL
handoff.

Two consequences that shape the whole design:

1. **No server changes are needed.** `HOST` stays `127.0.0.1`
   (`app/config.py:21`); the Sonos never resolves a Hum URL, so signed URLs, the
   host allowlist, and all three invariants are untouched. This is a
   frontend-only feature.
2. **MSE output cannot be routed.** hls.js feeds the element a blob URL, and
   AirPlay has nothing to hand off or re-encode from a blob in the way the
   element-level route expects. This is the live-playback problem in §3.

⚠️ Consequence 1 is inferred from documented protocol behavior, not measured on
this app. **Task 0 of the plan is to verify it empirically** before building on
it. If VOD-over-AirPlay turns out to need a LAN-reachable origin, the scope
grows substantially (bind address, CORS origins, signed-URL audience) and this
design should be revisited rather than patched.

## Scope

In scope: an AirPlay button in the Player transport, availability-gated, for
**VOD playback**. Live playback gets a defined, honest behavior (§3) rather than
a silent failure.

Out of scope: Chromecast, multi-room grouping, AirPlay from iOS Safari (iOS has
no in-page picker; the system Control Center route is the answer there), and any
attempt to improve audio quality over the AirPlay path (protocol-capped).

## Section 1 — The button

Four WebKit APIs on `HTMLMediaElement`, none in `lib.dom.d.ts`:

| API | Use |
|---|---|
| `webkitShowPlaybackTargetPicker()` | Opens the native picker. Requires a user gesture. |
| `webkitplaybacktargetavailabilitychanged` | Event; `event.availability` is `"available"` / `"not-available"`. Gates button visibility. |
| `webkitCurrentPlaybackTargetIsWireless` | Boolean; drives the button's active state. |
| `webkitcurrentplaybacktargetiswirelesschanged` | Event; fires when the above flips. |

Design decisions:

- **Availability listener is mounted with the player, not globally.** Apple
  documents that monitoring availability costs battery. It attaches in the same
  `$effect` that owns the element and detaches on cleanup. Registering the
  listener immediately dispatches an initial event with current availability, so
  there's no separate "query current state" call.
- **Button is hidden, not disabled, when unavailable.** Every non-Safari browser
  reports nothing here; a permanently-disabled button in Chrome is noise.
- **`x-webkit-airplay="allow"`** on the `<audio>` element.
- **TypeScript declarations are required, not optional.** `svelte-check` runs in
  the gate (`scripts/check.sh`), so a `.d.ts` augmenting `HTMLAudioElement` with
  these four members must land in the same change or CI fails.

Placement: the transport row in `Player.svelte`, and the overlay controls in
`NowPlaying.svelte` — the existing pattern where both surfaces drive the same
element through `playerControls`.

## Section 2 — VOD (the path that works)

No changes needed to source selection. `pickVodSrc`
(`Player.svelte:17-21`) already hands Safari the native HLS URL
`/api/hls/{id}.m3u8` — signed at `app/api/video.py:47-49` — because `hlsNative`
is true there. That is a plain, receiver-fetchable, non-MSE source, which is
exactly what the route wants.

The one thing to verify: the signed HLS URL carries an expiry
(`stream_url_ttl_seconds`, default 6 h). If the route survives past expiry, the
element errors and `handleError` (`Player.svelte:327+`) does its refetch dance —
which swaps `src`, which **drops the AirPlay route**. Task 3 covers re-asserting
the route after a recovery swap, or accepting the drop and documenting it.

## Section 3 — Live (the path that breaks)

`Player.svelte:170-242` attaches hls.js whenever `Hls.isSupported()`, true in
desktop Safari. MSE → blob URL → not routable. Left alone, the user taps AirPlay
during a live stream and gets either a refused route or audio that keeps playing
locally — a silent failure, which this repo's conventions specifically reject.

Three options, in the order I'd try them:

**A. hls.js `MEDIA_ATTACHING` workaround (try first).** Do the AirPlay setup
during hls.js's `MEDIA_ATTACHING` event. This is what Stremio landed
(`Stremio/stremio-video` PR #74) for the same problem. Cheapest if it works;
keeps hls.js's recovery logic intact.

**B. Force the native-HLS branch while a route is active.** `Player.svelte:243-245`
already has this branch for iOS Safari (`audio.src = src`). When an AirPlay
target connects, tear down hls.js and switch to it; re-attach hls.js on
disconnect. Costs the recovery logic that the comment at `Player.svelte:165-168`
says is the entire reason hls.js is there for live — playlist refresh, segment
scheduling, discontinuity handling. A live stream that hiccups while routed will
recover worse.

**C. Hide the button for live tracks.** Honest, trivially correct, zero risk.
The fallback if A and B both fail.

// DECISION: try A, fall back to B, ship C if neither holds. **Never ship the
silent failure.** Whichever lands, the button's state must tell the truth about
whether the route will work.

## Testing

- **Unit (vitest):** button visibility against mocked availability events;
  cleanup detaches listeners; live-track behavior matches whichever option
  landed. The WebKit APIs are absent in jsdom, so they get mocked onto the
  element — this tests our logic, not Safari.
- **Manual, and it is the real gate.** None of this is verifiable in CI: no
  Safari, no Sonos. A `docs/PLAYBOOKS.md` entry should cover: VOD route +
  disconnect, live behavior, expiry recovery while routed, and the non-Safari
  no-button case. Manual verification is load-bearing here in a way it isn't
  elsewhere in this repo.

## Risks

| Risk | Handling |
|---|---|
| The no-server-change premise (§Problem) is wrong. | Task 0 verifies before anything is built. If wrong, revisit this design. |
| Live can't be routed at all. | Option C — hide the button — is always available and always honest. |
| Expiry recovery drops the route mid-listen. | Task 3; may end up documented rather than fixed. |
| WebKit APIs are non-standard and unversioned. | Feature-detect every one; also detect the standard `remote.prompt()` so a future standards-based path is a small edit. |
| Sonos's AirPlay 2 implementation differs from a HomePod's. | Manual testing is against the actual target hardware, not a proxy. |

## Non-goals reaffirmed

This adds no server surface, no new route, no new signed-URL type, and no change
to `app/models.py` / `frontend/src/lib/types.ts`. If an implementation finds
itself touching any of those, that's a signal the premise in §Problem broke —
stop and revisit.
