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

  // Picker fn is the minimum; the availability event is dispatched by Safari
  // alongside it. If the picker exists, we assume the event machinery does.
  function isSupportedEl(el: AirplayEl): boolean {
    return hasPicker(el);
  }

  function attach(audio: AirplayEl) {
    detach();
    el = audio;
    // A no-op element (jsdom, non-Safari): nothing to wire. isSupportedEl
    // returns false, the button stays hidden.
    if (!hasPicker(audio)) return;

    onAvail = (e) => {
      // Safari fires a native event with `.availability` directly on it;
      // the test dispatches a CustomEvent, which carries payload under
      // `.detail` instead. Accept either shape.
      const availability = (e as any).detail?.availability ?? e.availability;
      state.available = availability === 'available';
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
    isSupportedEl,
  };
}
