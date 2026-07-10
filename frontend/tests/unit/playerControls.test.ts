import { describe, it, expect, afterEach } from 'vitest';
import { playerControls } from '../../src/lib/store.svelte';

describe('playerControls', () => {
  afterEach(() => {
    // Restore null between tests so state doesn't leak.
    playerControls.current = null;
  });

  it('starts unregistered', () => {
    expect(playerControls.current).toBeNull();
  });

  it('can be set and cleared', () => {
    const fake = {
      play: () => {},
      pause: () => {},
      toggle: () => {},
      seekBy: () => {},
      setVolume: () => {},
      toggleMute: () => {},
      getPosition: () => 0,
      restoreAt: () => {},
    };
    playerControls.current = fake;
    expect(playerControls.current).toBe(fake);
    playerControls.current = null;
    expect(playerControls.current).toBeNull();
  });

  it('getPosition is callable and returns a number', () => {
    const fake = {
      play: () => {}, pause: () => {}, toggle: () => {},
      seekBy: () => {}, setVolume: () => {}, toggleMute: () => {},
      getPosition: () => 42,
      restoreAt: () => {},
    };
    playerControls.current = fake;
    expect(playerControls.current!.getPosition!()).toBe(42);
  });

  it('restoreAt is callable with a position', () => {
    let restored: number | null = null;
    const fake = {
      play: () => {}, pause: () => {}, toggle: () => {},
      seekBy: () => {}, setVolume: () => {}, toggleMute: () => {},
      getPosition: () => 0,
      restoreAt: (pos: number) => { restored = pos; },
    };
    playerControls.current = fake;
    playerControls.current!.restoreAt!(12.5);
    expect(restored).toBe(12.5);
  });
});
