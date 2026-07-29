import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import NowPlaying from '../../src/components/NowPlaying.svelte';
import { store, playerControls } from '../../src/lib/store.svelte';
import type { Track } from '../../src/lib/types';

const sampleTrack = (id: string, audioUrl: string): Track => ({
  videoId: id,
  title: `Track ${id}`,
  author: 'A',
  durationSeconds: 100,
  thumbnailUrl: '',
  audioUrl,
  itag: 140,
});

beforeEach(() => {
  store.clear();
  store.player.current = null;
  store.player.isExpanded = false;
  store.player.airplayCapable = false;
  playerControls.current = null;
});

describe('NowPlaying — AirPlay button gating', () => {
  it('does not render the airplay button when airplayCapable is false', async () => {
    store.playNow(sampleTrack('abc', '/proxy/audio/abc?itag=140&exp=1&sig=' + 'a'.repeat(32)));
    store.expandPlayer();
    store.player.airplayCapable = false;
    playerControls.current = {
      play: () => {}, pause: () => {}, toggle: () => {},
      seekBy: () => {}, setVolume: () => {}, toggleMute: () => {},
      showPlaybackTargetPicker: () => {},
    };
    const { container } = render(NowPlaying);
    await tick();
    expect(container.querySelector('[aria-label="AirPlay"]')).toBeNull();
  });

  it('renders the airplay button when airplayCapable flips true AFTER mount', async () => {
    // This is the real lifecycle: Player's $effect sets airplayCapable on the
    // reactive store AFTER NowPlaying has rendered, when the availability event
    // arrives. The flag lives in store.player (a $state), so the flip must
    // re-render NowPlaying and surface the button. (C1 regression guard: the
    // flag previously lived on the non-reactive playerControls object and the
    // post-mount mutation never reached the template.)
    store.playNow(sampleTrack('abc', '/proxy/audio/abc?itag=140&exp=1&sig=' + 'a'.repeat(32)));
    store.expandPlayer();
    store.player.airplayCapable = false;
    playerControls.current = {
      play: () => {}, pause: () => {}, toggle: () => {},
      seekBy: () => {}, setVolume: () => {}, toggleMute: () => {},
      showPlaybackTargetPicker: () => {},
    };
    const { container } = render(NowPlaying);
    await tick();
    expect(container.querySelector('[aria-label="AirPlay"]')).toBeNull();

    // Player's effect fires this after the availability event arrives.
    store.player.airplayCapable = true;
    await tick();
    expect(container.querySelector('[aria-label="AirPlay"]')).not.toBeNull();
  });
});
