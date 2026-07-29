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
