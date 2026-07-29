import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
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
  playerControls.current = null;
});

describe('NowPlaying — AirPlay button gating', () => {
  it('does not render the airplay button when airplayCapable is falsy', async () => {
    store.playNow(sampleTrack('abc', '/proxy/audio/abc?itag=140&exp=1&sig=' + 'a'.repeat(32)));
    store.expandPlayer();
    // Simulate a Player that attached controls but found no AirPlay support:
    // the capability flag is absent, exactly as it is under jsdom.
    playerControls.current = {
      play: () => {}, pause: () => {}, toggle: () => {},
      seekBy: () => {}, setVolume: () => {}, toggleMute: () => {},
      showPlaybackTargetPicker: () => {},
      // airplayCapable intentionally omitted (undefined)
    };
    const { container } = render(NowPlaying);
    const btn = container.querySelector('[aria-label="AirPlay"]');
    expect(btn).toBeNull();
  });

  it('renders the airplay button when airplayCapable is true', async () => {
    store.playNow(sampleTrack('abc', '/proxy/audio/abc?itag=140&exp=1&sig=' + 'a'.repeat(32)));
    store.expandPlayer();
    playerControls.current = {
      play: () => {}, pause: () => {}, toggle: () => {},
      seekBy: () => {}, setVolume: () => {}, toggleMute: () => {},
      showPlaybackTargetPicker: () => {},
      airplayCapable: true,
    };
    const { container } = render(NowPlaying);
    const btn = container.querySelector('[aria-label="AirPlay"]');
    expect(btn).not.toBeNull();
  });
});
