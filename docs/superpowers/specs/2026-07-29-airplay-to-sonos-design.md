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
it, with an explicit falsifier:

- **Pass:** with `HOST=127.0.0.1` unchanged, AirPlay a VOD track from Safari to
  the Sonos — audio plays. (The speaker never fetched a Hum URL.)
- **Fail:** Safari or the Sonos attempts a request to a `127.0.0.1` URL it
  would have to resolve — i.e. the route only works if the receiver can reach
  the origin. Watch the browser network panel and the Sonos for any such fetch.

If Task 0 fails, the scope grows substantially (bind address, CORS origins,
signed-URL audience) and this design should be revisited rather than patched.

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
- **Disconnect mid-playback:** when the wireless route drops mid-track (Sonos
  powered off, network blip), `webkitcurrentplaybacktargetiswirelesschanged`
  fires and the button reverts to inactive. Local playback **continues at the
  current position** — no stall, no restart. The route is not auto-re-engaged;
  the user re-taps if they want it back.
- **Track-skip while routed:** the route persists across track changes — the new
  track plays on the Sonos. `src` swaps via `pickVodSrc` must not tear the route
  down; this is verified alongside the recovery-swap case in Task 3, since both
  are src-swap events.
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
(`stream_url_ttl_seconds`, default 6 h). If a session outlasts it, the element
errors and `handleError` (`Player.svelte:327+`) does its refetch dance — which
swaps `src`, which **drops the AirPlay route**. (The expiry is on the signed
URL, not on the route itself; the Mac has already been fetching and re-encoding,
so it bites when the element re-requests segments, not on every packet.)
Task 3 **auto re-asserts** the route after the recovery swap completes, so
playback continues uninterrupted on the Sonos. The re-assert is verified as part
of the same src-swap test as track-skip (§1), since both are src-swap events.

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

**Pass/fail per option** (the observable that triggers fallback to the next):
- **A passes iff:** with hls.js attached and a target connected,
  `webkitCurrentPlaybackTargetIsWireless === true` **and** audio is audible on
  the Sonos through a 60s live segment with no fatal `Hls.Error`. If audio
  never surfaces or a fatal error fires within that window → A fails, try B.
- **B passes iff:** after tearing down hls.js and setting `audio.src = src`,
  the same target-connected + audible-for-60s contract holds. Re-attach of
  hls.js on disconnect must resume at the live edge (no stall, no manual seek).
- **C** is unconditional — live tracks simply don't show the button.

## Testing

**Unit (vitest)** — what it observably proves, and what it doesn't:
- The WebKit APIs are absent in jsdom, so they get mocked onto the element.
  This tests **our logic, not Safari**: it proves that given a mocked
  `availability` event the button's bound `hidden` state flips, and that after
  unmount a further dispatch no longer mutates state (detach **by behaviour**,
  not by a `removeEventListener` spy — a spy only proves the call was made, not
  that the name matched a registered listener).
- It does **not** prove: that the listener registers on the real Safari element,
  that `webkitShowPlaybackTargetPicker` is called inside a user gesture (jsdom
  has no gesture semantics), or that detach removes the Safari-side listener by
  name. Those are manual.
- Cases: dispatch `webkitplaybacktargetavailabilitychanged` with `"available"` →
  button `hidden` is false; dispatch `"not-available"` → true; after unmount,
  the same dispatch is a no-op; the magic string `webkitplaybacktargetavailabilitychanged`
  is asserted verbatim (it appears four times across four identifiers; a typo
  would pass jsdom silently).

**Feature-detection contract** (the minimum API subset, testable as a pure
boolean `airplaySupported(el)`):
- Button **renders** iff `el.webkitShowPlaybackTargetPicker` is a function. This
  is the minimum.
- Button is **functional** iff that *plus* the `availability`-event mechanism is
  present (the event name constant is reachable). Partial support — picker
  present but no `availabilitychanged` — renders the button but leaves it
  permanently in its initial state; treat as unsupported and hide.
- The standard `remote.prompt()` (Remote Playback API) is feature-detected
  alongside, so a future standards-based path is a small edit. If both exist,
  prefer the WebKit API on Safari (the standard is poorly adopted there).

**Manual, and it is the real gate.** None of this is verifiable in CI: no
Safari, no Sonos. The gate is a binary-outcome checklist, **with the Sonos model
and firmware recorded alongside the results** so it's reproducible. Minimum
entries:

1. **Task 0 (no-server-change premise):** `HOST=127.0.0.1` unchanged, AirPlay a
   VOD track from Safari → Sonos. Pass = audio plays and the browser/Sonos makes
   **no** fetch to a `127.0.0.1` URL. Fail = such a fetch appears.
2. **VOD route:** open picker → Sonos appears in list within ~2s → select →
   audio surfaces from the speaker, system output unchanged.
3. **Disconnect mid-playback:** pull the route (power off Sonos / network blip)
   → button reverts to inactive, local playback continues at current position.
4. **Track-skip while routed:** next track → audio continues on the Sonos (route
   persists).
5. **Expiry recovery while routed:** force URL expiry → `handleError` recovery
   swap fires → route auto re-asserts → audio continues on the Sonos.
6. **Live (whichever of A/B/C landed):** per the §3 pass/fail contract.
7. **Non-Safari (negative):** open in Chrome → no AirPlay button renders.

Record results against a named Sonos model (e.g. `Sonos Era 100, S2 15.x`).
A `docs/PLAYBOOKS.md` entry names this checklist so a CI grep can confirm it
landed.

## Risks

| Risk | Handling |
|---|---|
| The no-server-change premise (§Problem) is wrong. | Task 0 verifies before anything is built. If wrong, revisit this design. |
| Live can't be routed at all. | Option C — hide the button — is always available and always honest. |
| Expiry recovery drops the route mid-listen. | Task 3 auto-re-asserts the route after the recovery swap (decided — see §2). |
| WebKit APIs are non-standard and unversioned. | Feature-detect every one; also detect the standard `remote.prompt()` so a future standards-based path is a small edit. |
| Sonos's AirPlay 2 implementation differs from a HomePod's. | Manual testing is against the actual target hardware, not a proxy. |

## Non-goals reaffirmed

This adds no server surface, no new route, no new signed-URL type, and no change
to `app/models.py` / `frontend/src/lib/types.ts`. If an implementation finds
itself touching any of those, that's a signal the premise in §Problem broke —
stop and revisit.

## Clarifications (2026-07-29)

From the GLM review panel (3 lenses). Resolved findings folded into the body
above; the four product/build decisions recorded here.

- **Q (lens A/B/C): track-skip while routed** → **A:** the route persists across
  track changes; the new track plays on the Sonos. Matches native-media-app
  behaviour. `src` swaps via `pickVodSrc` must not tear the route down — verify
  in Task 3 alongside the recovery-swap case, since both are src-swap events.
- **Q (lens A/C): expiry-induced recovery swap drops the route** → **A:** auto
  re-assert. After `handleError`'s `src` swap completes, programmatically
  re-engage the AirPlay route so playback continues uninterrupted on the Sonos.
  Replaces the "or accept the drop and document it" hedge in §2.
- **Q (lens C): live A→B→C sequencing needs hardware** → **A:** the dev machine
  is a Mac — Safari is local, so validation does not block on external hardware.
  Withdraw the C-first-MVP recommendation: build the full A→B→C chain and
  validate locally. (Sonos is still required for the final manual gate, but not
  for iterating on the hls.js workaround.)
- **Q (lens B): AirPlay picker entry across both surfaces** → **A:** add a new
  `playerControls` method (`showPlaybackTargetPicker`). `NowPlaying.svelte`
  reaches the element via `document.querySelector('audio')` for scrub/restart
  (`NowPlaying.svelte:17,47,59`), not through `playerControls` — the AirPlay
  action gets a shared entry point instead, matching the `toggle()` pattern
  (`store.svelte.ts:24`, `NowPlaying.svelte:54`).

## Panel follow-ups

All four must-resolve / should-clarify items from the run report have been
folded into the body: Task 0 falsifier (§Problem), option pass/fail contract
(§3), disconnect mid-playback (§1), and the manual-gate checklist + feature-detect
contract + vitest scope (§Testing). The risk table's expiry row was updated to
match the auto-re-assert decision.
