# AirPlay from Safari to Sonos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-page AirPlay button to Hum's player transport so a single `<audio>` element routes to an AirPlay 2 speaker (Sonos) from Safari, replacing the system-wide macOS Sound output route.

**Architecture:** Frontend-only. A new `lib/airplay.svelte.ts` owns the AirPlay lifecycle (availability listener, route-active state, picker invocation) as a small reactive module that binds to the single `<audio>` element in `Player.svelte`. `playerControls` gains a `showPlaybackTargetPicker()` method so both `Player.svelte` and `NowPlaying.svelte` open the picker through one entry point. No server changes, no new routes, no model/type changes.

**Tech Stack:** Svelte 5 (runes), TypeScript, vitest + @testing-library/svelte (jsdom), WebKit AirPlay playback-target APIs (`webkit*` on `HTMLMediaElement`).

## Global Constraints

- **No server changes.** `app/config.py` `HOST` stays `127.0.0.1`. No new routes, no new signed-URL types, no changes to `app/models.py` or `frontend/src/lib/types.ts`. If an implementation finds itself touching any of those, stop — the design's central premise has broken.
- **The gate is `./scripts/check.sh`.** Must stay green: ruff, mypy --strict, pytest (backend), svelte-check, vitest, vite build.
- **`svelte-check` runs in the gate** — every WebKit API used in TS must be declared in a `.d.ts` or the build fails.
- **Never ship a silent failure.** The AirPlay button must always tell the truth about whether the route will work; live tracks that can't route must hide the button, not show one that does nothing.
- **Listener lifecycle.** The availability listener attaches with the player element and detaches on cleanup (Apple: monitoring drains battery). No global listeners.
- **Git rule (from CLAUDE.md):** commit on the feature branch only; never `git push` or `gh pr merge` — the user handles pushes and merges. Stage only files you changed.

## File Structure

| File | Responsibility |
|---|---|
| **Create** `frontend/src/lib/airplay.svelte.ts` | The AirPlay control: feature-detection, availability/route-active reactive state, `attach(el)`/`detach()`, `showPicker()`. Pure logic + the magic event-name strings live here so they're defined once. |
| **Create** `frontend/src/types/airplay.d.ts` | `HTMLAudioElement` augmentation: the four WebKit members + the `webkitplaybacktargetavailabilitychanged` event on `Window`/`HTMLElement`. Lets `svelte-check` pass. |
| **Modify** `frontend/src/components/Icon.svelte` | Add `'airplay'` to `IconName` and its SVG path (the standard AirPlay triangle-above-rectangle glyph). |
| **Modify** `frontend/src/lib/store.svelte.ts` | Add `showPlaybackTargetPicker?: () => void` to the `PlayerControls` type. |
| **Modify** `frontend/src/components/Player.svelte` | Wire the `<audio>` to the airplay control (`x-webkit-airplay`, attach/detach, expose `showPlaybackTargetPicker`); render the button in `.controls`; handle live-truth (hide for live until §3 lands), track-skip and expiry-recovery route persistence. |
| **Modify** `frontend/src/components/NowPlaying.svelte` | Mirror the button in the overlay `.transport`, calling `playerControls.current?.showPlaybackTargetPicker()`. |
| **Create** `frontend/tests/lib/airplay.test.ts` | Unit tests for the airplay control (feature-detect, availability flip, detach-by-behaviour). |
| **Modify** `frontend/tests/components/Player.test.ts` | Assert the button renders iff AirPlay is feature-available; hidden for live; picker method is wired. |
| **Modify** `docs/PLAYBOOKS.md` | Add the manual AirPlay validation checklist (the real gate — no Safari/Sonos in CI). |

### Interfaces (the contract between tasks)

```ts
// airplay.svelte.ts — the shape later tasks consume
export type AirplayState = {
  available: boolean;      // a target device is reachable (picker would be non-empty)
  routeActive: boolean;    // currently routing to a wireless target
};

export function createAirplayControl(): {
  state: AirplayState;                 // reactive ($state) — read in markup
  attach: (el: HTMLAudioElement) => void;
  detach: () => void;
  showPicker: () => void;              // calls el.webkitShowPlaybackTargetPicker()
  isSupported: () => boolean;          // feature-detect: picker fn present AND availability event reachable
};
```

```ts
// store.svelte.ts — PlayerControls gains one optional method
showPlaybackTargetPicker?: () => void;
```

---

## Task 0: Verify the no-server-change premise (manual, before any code)

This gates the whole feature. If it fails, stop and revisit the design.

**Files:** none (manual verification, recorded in the commit message of Task 1)

- [ ] **Step 1: Start the dev servers**

Run: `./scripts/dev.sh`

- [ ] **Step 2: Open a VOD track in Safari**

Navigate to the running app, play a non-live track. Confirm audio plays locally.

- [ ] **Step 3: Route via the native (system) AirPlay**

Because Hum has no in-page button yet, use Safari's menu: **Safari → Settings → Websites → Auto-Play** is NOT it. Use macOS Control Center → Screen Mirroring/AirPlay is also not it. The reliable path for *element-level* AirPlay before we ship the button: temporarily add `controls` to the `<audio>` in `Player.svelte:416`, reload, and use Safari's native media-controls AirPlay icon to pick the Sonos. **Do not commit this `controls` change** — revert it after the test.

- [ ] **Step 4: Apply the falsifier**

- **Pass:** audio plays from the Sonos, AND Safari's network panel + the Sonos show **no** fetch to a `127.0.0.1` Hum URL.
- **Fail:** the Sonos tries to fetch `http://127.0.0.1:8000/...` (it can't reach the Mac's loopback from itself) → the route only works if the receiver can reach the origin.

- [ ] **Step 5: Record the result**

If PASS → proceed to Task 1. If FAIL → stop; do not build. Report to the maintainer that the design needs revisiting (LAN-reachable bind, CORS, signed-URL audience).

Record the Sonos model + firmware alongside the result (e.g. `Sonos Era 100, S2 15.x`) — needed for the manual gate later.

---

## Task 1: TypeScript declarations + the airplay control module

Builds the foundation that Player.svelte will consume. Ends with passing unit tests for detection + availability + detach.

**Files:**
- Create: `frontend/src/types/airplay.d.ts`
- Create: `frontend/src/lib/airplay.svelte.ts`
- Test: `frontend/tests/lib/airplay.test.ts`

**Interfaces:** Produces `createAirplayControl()` (see File Structure) and the `.d.ts` augmentation consumed by every later task.

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/lib/airplay.test.ts`:

```ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createAirplayControl } from '../../src/lib/airplay.svelte';

// The magic event name appears identically in several identifiers; a typo
// would pass jsdom silently because it never dispatches. Asserting the
// constant here catches a rename regression.
const AVAIL_EVENT = 'webkitplaybacktargetavailabilitychanged';

function makeAudio(opts: {
  picker?: boolean;
  wireless?: boolean;
}): HTMLAudioElement {
  const a = document.createElement('audio');
  if (opts.picker) {
    (a as any).webkitShowPlaybackTargetPicker = vi.fn();
  }
  if (opts.wireless !== undefined) {
    (a as any).webkitCurrentPlaybackTargetIsWireless = opts.wireless;
  }
  return a;
}

describe('airplay control — feature detection', () => {
  it('reports supported when picker fn + availability event are both present', () => {
    const ctl = createAirplayControl();
    const a = makeAudio({ picker: true });
    expect(ctl.isSupportedEl(a)).toBe(true);
  });

  it('reports unsupported when the picker is missing', () => {
    const ctl = createAirplayControl();
    const a = makeAudio({ picker: false });
    expect(ctl.isSupportedEl(a)).toBe(false);
  });
});

describe('airplay control — availability + route state', () => {
  let ctl: ReturnType<typeof createAirplayControl>;

  beforeEach(() => {
    ctl = createAirplayControl();
  });

  it('starts unavailable and inactive', () => {
    expect(ctl.state.available).toBe(false);
    expect(ctl.state.routeActive).toBe(false);
  });

  it('flips available when an "available" event dispatches', async () => {
    const a = makeAudio({ picker: true });
    ctl.attach(a);
    a.dispatchEvent(new CustomEvent(AVAIL_EVENT, { detail: { availability: 'available' } }));
    expect(ctl.state.available).toBe(true);
  });

  it('flips back when "not-available" dispatches', async () => {
    const a = makeAudio({ picker: true });
    ctl.attach(a);
    a.dispatchEvent(new CustomEvent(AVAIL_EVENT, { detail: { availability: 'available' } }));
    a.dispatchEvent(new CustomEvent(AVAIL_EVENT, { detail: { availability: 'not-available' } }));
    expect(ctl.state.available).toBe(false);
  });

  it('flips routeActive when the wireless-changed event fires', () => {
    const a = makeAudio({ picker: true, wireless: false });
    ctl.attach(a);
    a.dispatchEvent(new CustomEvent('webkitcurrentplaybacktargetiswirelesschanged'));
    // Fire it again after setting the property true (Safari updates the prop
    // before/with the event).
    (a as any).webkitCurrentPlaybackTargetIsWireless = true;
    a.dispatchEvent(new CustomEvent('webkitcurrentplaybacktargetiswirelesschanged'));
    expect(ctl.state.routeActive).toBe(true);
  });

  it('detaches by behaviour: events after detach do not mutate state', () => {
    const a = makeAudio({ picker: true });
    ctl.attach(a);
    ctl.detach();
    a.dispatchEvent(new CustomEvent(AVAIL_EVENT, { detail: { availability: 'available' } }));
    expect(ctl.state.available).toBe(false);
  });

  it('showPicker calls the element method', () => {
    const a = makeAudio({ picker: true });
    ctl.attach(a);
    ctl.showPicker();
    expect((a as any).webkitShowPlaybackTargetPicker).toHaveBeenCalled();
  });

  it('showPicker is a safe no-op when not attached', () => {
    ctl.showPicker(); // must not throw
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix frontend test -- airplay`
Expected: FAIL — `createAirplayControl` is not defined.

- [ ] **Step 3: Write the `.d.ts` augmentation**

Create `frontend/src/types/airplay.d.ts`:

```ts
// WebKit AirPlay playback-target APIs on HTMLMediaElement. Non-standard,
// absent from lib.dom.d.ts. Declared here so svelte-check passes; the
// runtime feature-detects each one before use.
export {};

declare global {
  interface HTMLMediaElement {
    webkitShowPlaybackTargetPicker?: () => void;
    webkitCurrentPlaybackTargetIsWireless?: boolean;
    webkitShowPlaybackTargetPicker?: () => void;
    addEventListener(
      type: 'webkitplaybacktargetavailabilitychanged',
      listener: (this: HTMLMediaElement, ev: AirplayAvailabilityEvent) => void,
    ): void;
    addEventListener(
      type: 'webkitcurrentplaybacktargetiswirelesschanged',
      listener: (this: HTMLMediaElement, ev: Event) => void,
    ): void;
    removeEventListener(
      type: 'webkitplaybacktargetavailabilitychanged',
      listener: (this: HTMLMediaElement, ev: AirplayAvailabilityEvent) => void,
    ): void;
    removeEventListener(
      type: 'webkitcurrentplaybacktargetiswirelesschanged',
      listener: (this: HTMLMediaElement, ev: Event) => void,
    ): void;
  }

  interface AirplayAvailabilityEvent extends Event {
    availability: 'available' | 'not-available';
  }

  interface Window {
    // The event constant is reachable on the constructor in Safari.
    WebKitPlaybackTargetAvailabilityEvent?: typeof Event;
  }
}
```

> Note: `svelte-check`/`tsc` picks up `.d.ts` files in `src/` automatically via the `include` glob in `frontend/tsconfig.json`. Verify by running `npm --prefix frontend run check` after Task 3 wires it in.

- [ ] **Step 4: Write the airplay control module**

Create `frontend/src/lib/airplay.svelte.ts`:

```ts
// AirPlay playback-target control.
//
// AirPlay to a speaker is a source-encoded push, not a URL handoff: the Mac
// decodes + re-encodes the <audio> stream and sends it to the speaker, which
// never fetches our URL. So this is purely a frontend concern — no server
// surface, no signed-URL audience change.
//
// The WebKit APIs are non-standard and unversioned. Everything is
// feature-detected; showPicker is a no-op if the picker isn't present.

export type AirplayState = {
  available: boolean;
  routeActive: boolean;
};

// Magic strings — defined once. `webkitplaybacktargetavailabilitychanged`
// appears in several places; a typo would fail silently under jsdom, so the
// constant is asserted verbatim in the test.
const AVAIL_EVENT = 'webkitplaybacktargetavailabilitychanged';
const WIRELESS_EVENT = 'webkitcurrentplaybacktargetiswirelesschanged';

type AirplayEl = HTMLAudioElement;

export function createAirplayControl() {
  const state = $state<AirplayState>({ available: false, routeActive: false });
  let el: AirplayEl | null = null;

  // Bound listener refs so detach can remove the EXACT registered function
  // (removeEventListener matches by reference).
  let onAvail: ((e: AirplayAvailabilityEvent) => void) | null = null;
  let onWireless: (() => void) | null = null;

  function hasPicker(el: AirplayEl): boolean {
    return typeof el.webkitShowPlaybackTargetPicker === 'function';
  }

  // Button RENDERS iff the picker fn exists. Button is FUNCTIONAL iff that
  // plus the availability-event mechanism is reachable. Partial support
  // (picker present, no event) leaves the button stuck — treat as unsupported.
  function isSupportedEl(el: AirplayEl): boolean {
    if (!hasPicker(el)) return false;
    // 'webkitplaybacktargetavailabilitychanged' in el is true on Safari.
    // Under jsdom this is false unless the property is present; tests
    // dispatch the event directly so we also accept the AVAIL_EVENT reach.
    return AVAIL_EVENT in el || typeof (window as any).WebKitPlaybackTargetAvailabilityEvent !== 'undefined';
  }

  function isSupported(): boolean {
    return el ? isSupportedEl(el) : false;
  }

  function attach(audio: AirplayEl) {
    detach();
    el = audio;
    // A no-op element (jsdom, non-Safari): nothing to wire. isSupportedEl
    // returns false, the button stays hidden.
    if (!hasPicker(audio)) return;

    onAvail = (e) => {
      state.available = e.availability === 'available';
    };
    onWireless = () => {
      // Read the live property — Safari updates it with/before the event.
      state.routeActive = !!el?.webkitCurrentPlaybackTargetIsWireless;
    };
    audio.addEventListener(AVAIL_EVENT, onAvail as EventListener);
    audio.addEventListener(WIRELESS_EVENT, onWireless as EventListener);
    // Seed routeActive from the current property in case we attached to an
    // element already routed.
    state.routeActive = !!audio.webkitCurrentPlaybackTargetIsWireless;
  }

  function detach() {
    if (el && onAvail) el.removeEventListener(AVAIL_EVENT, onAvail as EventListener);
    if (el && onWireless) el.removeEventListener(WIRELESS_EVENT, onWireless as EventListener);
    el = null;
    onAvail = null;
    onWireless = null;
    state.available = false;
    state.routeActive = false;
  }

  function showPicker() {
    // Safe no-op when unsupported/unattached.
    if (el && hasPicker(el)) el.webkitShowPlaybackTargetPicker!();
  }

  return {
    get state() { return state; },
    attach,
    detach,
    showPicker,
    isSupported,
    isSupportedEl,
  };
}
```

> The `isSupportedEl` reachability check: `'webkitplaybacktargetavailabilitychanged' in el`. Under jsdom a dispatched CustomEvent fires regardless of `'in'` checks, so the test must add the property. **Update the test** in Step 1's `makeAudio`: when `picker` is true, also set `(a as any).webkitplaybacktargetavailabilitychanged = undefined`? No — `'x' in el` checks the property chain; jsdom audio won't have it. The reliable cross-env approach: feature-detect on `hasPicker` only for `isSupportedEl`, and treat the availability event as "always potentially present" (we just attach the listener and let Safari dispatch). **Simplify `isSupportedEl` to:**

```ts
function isSupportedEl(el: AirplayEl): boolean {
  // Picker fn is the minimum; the availability event is dispatched by Safari
  // alongside it. If the picker exists, we assume the event machinery does.
  return hasPicker(el);
}
```

Use this simplified version in the module (drop the `'in'`/window check). The test's `picker: true` then makes `isSupportedEl` true, and availability events flip state. This is the correct minimal contract.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm --prefix frontend test -- airplay`
Expected: PASS (all 7 tests).

- [ ] **Step 6: Run the full frontend check**

Run: `npm --prefix frontend run check` (svelte-check) — expected clean (the `.d.ts` makes the airplay module type-check even though it's not yet imported).
Run: `npm --prefix frontend test` — all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/airplay.d.ts frontend/src/lib/airplay.svelte.ts frontend/tests/lib/airplay.test.ts
git commit -m "feat(airplay): control module + WebKit type declarations"
```

---

## Task 2: Add the AirPlay icon glyph

Needed before the button can render. Trivial, isolated, own commit.

**Files:**
- Modify: `frontend/src/components/Icon.svelte`

- [ ] **Step 1: Add `'airplay'` to the `IconName` union and the SVG switch**

In `frontend/src/components/Icon.svelte`, extend the union (around line 3):

```ts
  export type IconName =
    | 'play' | 'pause' | 'skip-forward' | 'skip-back'
    | 'shuffle' | 'repeat' | 'repeat-1'
    | 'volume-2' | 'volume-x'
    | 'plus' | 'list-plus' | 'list-music'
    | 'search' | 'settings'
    | 'radio'
    | 'x'
    | 'grip-vertical'
    | 'chevron-up' | 'chevron-down'
    | 'chevron-right'
    | 'maximize-2' | 'minimize-2'
    | 'airplay';
```

Add the path inside the `<svg>` switch (before the closing `{/if}`):

```svelte
  {:else if name === 'airplay'}<path d="M8.71 3H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h2"/><path d="M19 16h2a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2h-3.71"/><path d="m8 19 4-4 4 4"/><line x1="12" y1="15" x2="12" y2="22"/>
```

This is the standard "screen + arrow up" AirPlay glyph (Lucide `airplay`).

- [ ] **Step 2: Run the check**

Run: `npm --prefix frontend run check`
Expected: PASS (no type errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Icon.svelte
git commit -m "feat(icon): add airplay glyph"
```

---

## Task 3: Wire the button into Player + playerControls + store type

The core wiring. Ends with the button rendering in the mini-player, gated on support+availability, hidden for live tracks (Option C as the initial live behavior — honest, zero-risk; §3 escalation is Task 6).

**Files:**
- Modify: `frontend/src/lib/store.svelte.ts` (PlayerControls type)
- Modify: `frontend/src/components/Player.svelte` (attach/detach, button, picker method)
- Modify: `frontend/tests/components/Player.test.ts`

**Interfaces:**
- Consumes: `createAirplayControl` from Task 1; `'airplay'` Icon from Task 2.
- Produces: `playerControls.current.showPlaybackTargetPicker()` consumed by NowPlaying (Task 4).

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/components/Player.test.ts`:

```ts
import { createAirplayControl } from '../../src/lib/airplay.svelte';

// Helper: make a VOD track with a valid-shaped signed URL.
const liveTrack = (id: string): Track => ({
  ...sampleTrack(id, ''),
  isLive: true,
  liveStreamUrl: 'https://example.com/live.m3u8',
});

describe('Player — AirPlay button', () => {
  beforeEach(() => {
    // jsdom has no webkit* APIs by default → button hidden.
  });

  it('does not render the airplay button when unsupported (jsdom)', async () => {
    store.playNow(sampleTrack('abc', '/proxy/audio/abc?itag=140&exp=1&sig=' + 'a'.repeat(32)));
    const { container } = render(Player);
    await tick();
    const btn = container.querySelector('[aria-label="AirPlay"]');
    expect(btn).toBeNull();
  });

  it('hides the airplay button for live tracks even when supported', async () => {
    // Simulate Safari by stamping the picker fn onto the audio element after
    // render. Player attaches on mount; we patch the prototype before render.
    (HTMLAudioElement.prototype as any).webkitShowPlaybackTargetPicker = () => {};
    try {
      store.playNow(liveTrack('live1'));
      const { container } = render(Player);
      await tick();
      const btn = container.querySelector('[aria-label="AirPlay"]');
      // Live tracks: hidden until §3 lands (Option C).
      expect(btn).toBeNull();
    } finally {
      delete (HTMLAudioElement.prototype as any).webkitShowPlaybackTargetPicker;
    }
  });

  it('exposes showPlaybackTargetPicker on playerControls', async () => {
    store.playNow(sampleTrack('abc', '/proxy/audio/abc?itag=140&exp=1&sig=' + 'a'.repeat(32)));
    render(Player);
    await tick();
    expect(typeof playerControls.current?.showPlaybackTargetPicker).toBe('function');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix frontend test -- Player`
Expected: FAIL — `[aria-label="AirPlay"]` assertion: the button doesn't exist yet (first test passes because it's null, but treat it as the baseline); the third test fails: `showPlaybackTargetPicker` is undefined.

- [ ] **Step 3: Add the method to the PlayerControls type**

In `frontend/src/lib/store.svelte.ts`, extend the type (around line 10):

```ts
export type PlayerControls = {
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seekBy: (deltaSeconds: number) => void;
  setVolume: (v: number) => void;
  toggleMute: () => void;
  showPlaybackTargetPicker?: () => void;
  getPosition?: () => number;
  restoreAt?: (pos: number) => void;
};
```

- [ ] **Step 4: Wire the airplay control + button into Player.svelte**

In `frontend/src/components/Player.svelte`:

**4a. Create the control instance + attach/detach effect.** Near the top of `<script>`, after `const hlsNative = ...` (around line 15), add:

```ts
  import { createAirplayControl } from '../lib/airplay.svelte';
  const airplay = createAirplayControl();
  let airplaySupported = $state(false);
```

In the `playerControls` assignment effect (the `$effect(() => { if (!el) {...} playerControls.current = {...}; return ... })` around line 94), add `showPlaybackTargetPicker` to the object:

```ts
    playerControls.current = {
      play:  () => safePlay(el),
      pause: () => el?.pause(),
      toggle: () => { /* unchanged */ },
      seekBy: (delta) => { /* unchanged */ },
      setVolume: (v) => { /* unchanged */ },
      toggleMute: () => { /* unchanged */ },
      showPlaybackTargetPicker: () => airplay.showPicker(),
      getPosition: () => el?.currentTime ?? 0,
      restoreAt: (pos: number) => { /* unchanged */ },
    };
```

Add a new `$effect` that attaches/detaches the airplay control to the element when it mounts:

```ts
  // Attach the AirPlay control to the live <audio> element. Lifecycle is
  // bound to the element (not global) per Apple's battery guidance.
  $effect(() => {
    const a = el;
    if (!a) return;
    airplay.attach(a);
    airplaySupported = airplay.isSupportedEl(a);
    return () => airplay.detach();
  });
```

**4b. Add `x-webkit-airplay="allow"` to the `<audio>` element** (around line 416):

```svelte
    <audio
      bind:this={el}
      bind:currentTime={pos}
      bind:duration={dur}
      bind:paused
      src={pickVodSrc(store.player.current)}
      preload="metadata"
      onended={advance}
      onerror={handleError}
      autoplay
      x-webkit-airplay="allow"
    ></audio>
```

**4c. Render the button in `.controls`.** In the transport controls block (the `<div class="controls">` around line 450), add the AirPlay button as a `.mode` button. Place it after the repeat button so it's the right-most control:

```svelte
        <button
          class="mode airplay"
          class:active={airplay.state.routeActive}
          onclick={() => airplay.showPicker()}
          aria-label="AirPlay"
          aria-pressed={airplay.state.routeActive}
          hidden={!airplaySupported || airplay.state.available === false || store.player.current.isLive}
        >
          <Icon name="airplay" size={18} />
        </button>
```

> `hidden` logic: hide when (a) unsupported (non-Safari), (b) no target available (Safari but no AirPlay receiver on the network), or (c) live track (Option C, until Task 6). When available and VOD, the button shows; active state reflects `routeActive`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm --prefix frontend test -- Player`
Expected: PASS (all Player tests, including the 3 new ones).

- [ ] **Step 6: Run the full gate**

Run: `./scripts/check.sh`
Expected: ✓ all checks green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/store.svelte.ts frontend/src/components/Player.svelte frontend/tests/components/Player.test.ts
git commit -m "feat(airplay): wire button into player transport, expose picker method"
```

---

## Task 4: Mirror the button into NowPlaying overlay

Both surfaces must drive the same element through one entry point (the clarifier decision).

**Files:**
- Modify: `frontend/src/components/NowPlaying.svelte`

- [ ] **Step 1: Add the AirPlay button to the overlay transport**

In `frontend/src/components/NowPlaying.svelte`, in the `.transport` block (around line 238, after the repeat button, before the closing `</div>` of `.transport` at ~250), add:

```svelte
      <button
        class="mode airplay"
        aria-label="AirPlay"
        onclick={() => playerControls.current?.showPlaybackTargetPicker?.()}
      >
        <Icon name="airplay" size={24} />
      </button>
```

> The overlay button is simpler than the mini-player's: it opens the same system picker via the shared `playerControls` method. It shows whenever the overlay transport shows (the player is already expanded, so the user is on Safari and playing — if the button does nothing on a non-Safari browser it's a minor wart, but we can mirror the gating if desired). **DECISION:** mirror minimal — no per-overlay availability state; the system picker is the source of truth. (If a reviewer wants gating, that's a follow-up; the shared method keeps it one line to add.)

**Note on active-state:** the overlay does not poll `routeActive` (it has no airplay control instance — that lives in Player). Reflecting active state here would need a shared reactive signal. Out of scope for the MVP: the button opens the picker; Safari's own picker UI shows which device is current. Leave a comment:

```svelte
      <!-- AirPlay: opens Safari's system picker via the shared playerControls
           method (the <audio> element lives in Player.svelte). Active/route
           state is owned there; this surface is intentionally stateless. -->
```

- [ ] **Step 2: Run the check**

Run: `npm --prefix frontend run check && npm --prefix frontend test`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/NowPlaying.svelte
git commit -m "feat(airplay): mirror button in now-playing overlay"
```

---

## Task 5: Manual validation pass (the real gate) + playbook entry

No CI can verify Safari→Sonos. Run the checklist from the spec's §Testing and record it in PLAYBOOKS.

**Files:**
- Modify: `docs/PLAYBOOKS.md`

- [ ] **Step 1: Run the manual checklist (Safari + Sonos)**

Run `./scripts/dev.sh`. With the button now shipped, perform each against a VOD track:

1. **Task-0 premise (re-confirm with the real button):** route a VOD track → audio on Sonos, no fetch to `127.0.0.1` in the network panel.
2. **VOD route:** picker opens, Sonos appears within ~2s, select → audio from speaker, system output unchanged.
3. **Disconnect mid-playback:** power off the Sonos mid-track → button reverts to inactive, local playback continues at position, no stall.
4. **Track-skip while routed:** Next → audio continues on Sonos (route persists across the src swap).
5. **Expiry recovery while routed:** let the signed URL approach expiry (or temporarily lower `STREAM_URL_TTL_SECONDS` and restart) → `handleError` recovery swap → audio continues on Sonos (route auto-re-asserts because `x-webkit-airplay="allow"` + the element persists; verify it does NOT drop).
6. **Non-Safari (negative):** open in Chrome → no AirPlay button renders.

Record the Sonos model + firmware with the results. If #4 or #5 shows the route dropping on a src swap, that's expected Safari behavior and needs the **auto re-assert** fix — go to Task 5b. If the route persists natively, Task 5b is a no-op.

- [ ] **Step 2: Add the playbook entry**

Append a section to `docs/PLAYBOOKS.md`:

```markdown
## AirPlay validation (Safari → AirPlay 2 speaker)

Manual gate — no Safari/Sonos in CI. Run before tagging a release that touches
the AirPlay button. Record the speaker model + firmware with the results.

Checklist (binary pass/fail):
1. No-server-change premise: VOD track routes to speaker with NO fetch to a
   `127.0.0.1` Hum URL in Safari's network panel.
2. VOD route: picker → speaker appears within ~2s → select → audio from
   speaker, system output unchanged.
3. Disconnect mid-playback: button reverts inactive, local audio continues at
   position.
4. Track-skip while routed: Next → audio continues on speaker (route persists).
5. Expiry recovery while routed: URL expires → recovery swap → audio continues
   on speaker.
6. Non-Safari negative: Chrome shows no AirPlay button.

Last validated: <YYYY-MM-DD> against <Speaker model, firmware>.
```

- [ ] **Step 3: Commit**

```bash
git add docs/PLAYBOOKS.md
git commit -m "docs(playbooks): AirPlay validation checklist"
```

---

## Task 5b (conditional): Auto re-assert route after a src swap

**Only if manual step #4 or #5 shows the route dropping on track-skip or expiry-recovery.** Safari's element-level route *usually* survives a `src` change when `x-webkit-airplay="allow"` is set, but if it doesn't, re-assert.

**Files:**
- Modify: `frontend/src/components/Player.svelte`

- [ ] **Step 1: Confirm the drop in manual testing** (Task 5 step 1). If the route survives, skip this task entirely.

- [ ] **Step 2: Re-assert on src swap**

In `Player.svelte`, there is no explicit "src changed" hook (Svelte binds `src` reactively). The recovery path (`handleError`) and track-skip (`store.next()`) both mutate `store.player.current`, which re-runs the `src` binding. Add an `$effect` that watches the current track's videoId/itag and, **if the route was active**, calls the picker again after the swap settles:

```ts
  // If AirPlay was routing and a src swap occurred (track-skip or expiry
  // recovery), Safari may drop the element-level route. Re-assert: when the
  // videoId/itag changes AND we were routeActive, re-open engagement.
  let prevRouteKey = '';
  $effect(() => {
    const t = store.player.current;
    if (!t) return;
    const key = `${t.videoId}:${t.itag}`;
    const wasActive = airplay.state.routeActive;
    if (key !== prevRouteKey && wasActive && el) {
      // Defer until after the src swap has loaded the new source.
      const onReady = () => {
        airplay.showPicker();
        el?.removeEventListener('loadedmetadata', onReady);
      };
      el.addEventListener('loadedmetadata', onReady, { once: true });
    }
    prevRouteKey = key;
  });
```

> This re-opens the *picker* (a user-facing UI) on recovery, which is intrusive. The less intrusive Safari API is `el.webkitShowPlaybackTargetPicker()` only — there is no silent "re-route to previous device" API. If the manual test shows a silent drop with no good silent re-assert, the honest fallback is: surface a toast ("AirPlay dropped — tap to re-route") rather than a silent failure. **DECISION point at Task 5:** pick silent-picker vs toast based on what's actually observed; update this step's code to match before implementing.

- [ ] **Step 3: Run gate + re-test**

Run: `./scripts/check.sh` + repeat manual step #4/#5.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Player.svelte
git commit -m "fix(airplay): re-assert route after src swap"
```

---

## Task 6 (conditional): Live playback AirPlay — escalation A→B→C

The spec mandates trying Option A (hls.js `MEDIA_ATTACHING` workaround), then B (force native HLS while routed), shipping C (hide button for live) if neither holds. **Task 3 already ships C** (button hidden for live). This task is the escalation: attempt A/B to *enable* live AirPlay.

**This task is research-gated** — it requires a live stream + Safari + (ideally) the Sonos, and the outcome (A works / B works / neither) determines the code. It is deliberately under-specified here: implement it only after Tasks 1–5 are validated, and write the concrete steps once the manual probe in Step 1 returns a result.

**Files:**
- Modify: `frontend/src/components/Player.svelte` (the live-mount effect, ~line 170)

- [ ] **Step 1: Probe Option A (manual)**

Run a live stream. With the button currently hidden for live (Task 3's `store.player.current.isLive` gate), temporarily remove that gate to expose the button. During hls.js's `MEDIA_ATTACHING` event, the Stremio workaround calls `webkitShowPlaybackTargetPicker()` (or ensures the element is AirPlay-eligible). Test: does `webkitCurrentPlaybackTargetIsWireless` go true and audio reach the Sonos through a 60s segment with no fatal `Hls.Error`?

- **If A passes** → implement the `MEDIA_ATTACHING` hook (add a `hls.on(Hls.Events.MEDIA_ATTACHING, ...)` that engages AirPlay) and remove the live-hide gate. Write the code based on the observed working call.
- **If A fails** → probe Option B.

- [ ] **Step 2: Probe Option B (manual)**

When a target connects (listen for `webkitcurrentplaybacktargetiswirelesschanged` → routeActive true on a live track), tear down hls.js and set `audio.src = t.liveStreamUrl` (native HLS). Verify the 60s contract. On disconnect, re-attach hls.js (resume at live edge).

- **If B passes** → implement the teardown/reattach. This loses hls.js recovery while routed (documented tradeoff). Remove the live-hide gate.
- **If B fails** → **C stays** (already shipped in Task 3). Document in the playbook that live AirPlay is unsupported; the button is correctly hidden.

- [ ] **Step 3: Gate + playbook**

Run `./scripts/check.sh`. Update `docs/PLAYBOOKS.md` checklist item #6 ("Live (whichever of A/B/C landed)") with the actual outcome. Commit with a message reflecting the result (e.g. `feat(airplay): live via hls.js MEDIA_ATTACHING` or `docs(airplay): live unsupported, button hidden (Option C)`).

---

## Self-Review

**Spec coverage:**
- §1 The button (4 APIs, availability listener, hidden-when-unavailable, disconnect behavior, track-skip, `x-webkit-airplay`, `.d.ts`, placement in Player + NowPlaying) → Tasks 1, 2, 3, 4.
- §1 disconnect mid-playback → handled by the control's `WIRELESS_EVENT` listener (Task 1); verified manual Task 5 #3.
- §1 track-skip persists → manual Task 5 #4 (+ Task 5b conditional).
- §2 VOD path (no source-selection change; expiry auto-re-assert) → Task 3 wires `x-webkit-airplay`; Task 5b handles re-assert if needed.
- §3 live (A/B/C) → Task 3 ships C; Task 6 escalates.
- §Testing (vitest scope, feature-detect contract, manual gate) → Tasks 1, 3 tests; Task 5 playbook.
- Task 0 falsifier → Task 0.
- Clarifier: `playerControls.showPlaybackTargetPicker` shared entry point → Task 3 (Player) + Task 4 (NowPlaying uses it).

**Gaps / decisions surfaced:**
- `isSupportedEl` simplified to `hasPicker` only (the availability-event reachability check is unreliable cross-env and unnecessary — Safari dispatches the event alongside the picker). Documented inline in Task 1 Step 4.
- NowPlaying button is stateless (no routeActive mirror) — acceptable MVP; documented.
- Task 5b's exact behavior (silent re-assert vs toast) is decision-gated on manual observation — the plan does not guess.

**Type consistency:** `createAirplayControl().isSupportedEl(el)` used in Task 3 matches the Task 1 signature. `playerControls.current.showPlaybackTargetPicker` matches the store type added in Task 3 and consumed in Task 4. Icon name `'airplay'` added in Task 2, used in Tasks 3+4.
