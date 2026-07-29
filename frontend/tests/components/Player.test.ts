import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import Player from '../../src/components/Player.svelte';
import { store, playerControls } from '../../src/lib/store.svelte';
import type { Track, AudioFormat } from '../../src/lib/types';

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
  store.player.isPlaying = false;
  store.player.positionSeconds = 0;
});

describe('Player', () => {
  it('renders nothing visible when no current track', () => {
    const { container } = render(Player);
    expect(container.querySelector('.player.empty')).toBeTruthy();
  });

  it('shows the current track title', async () => {
    store.playNow(sampleTrack('abc', '/proxy/audio/abc?itag=140&exp=1&sig=' + 'a'.repeat(32)));
    const { findByText } = render(Player);
    expect(await findByText(/Track abc/)).toBeInTheDocument();
  });

  it('audio element src reflects current track URL', async () => {
    const url = '/proxy/audio/xyz?itag=140&exp=1&sig=' + 'b'.repeat(32);
    store.playNow(sampleTrack('xyz', url));
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement | null;
    expect(audio).not.toBeNull();
    expect(audio!.src).toContain('/proxy/audio/xyz');
  });

  it('playerControls.restoreAt seeks to position once metadata loads', async () => {
    store.playNow(sampleTrack('seek', '/proxy/audio/seek?itag=140&exp=1&sig=' + 'c'.repeat(32)));
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    playerControls.current!.restoreAt!(42);
    Object.defineProperty(audio, 'currentTime', { value: 0, writable: true });
    audio.dispatchEvent(new Event('loadedmetadata'));
    expect(audio.currentTime).toBe(42);
  });

  it('restoreAt waits for the NEW source even when the old one is already loaded', async () => {
    // Regression: switchQuality calls restoreAt synchronously right after
    // swapping the src, so at call time the element still holds the OLD,
    // fully-loaded (readyState 4) source. A readyState fast-path would seek the
    // doomed old source; the src swap then resets currentTime to 0 and the new
    // source loads with nothing listening — the seek is lost. restoreAt must
    // defer to the NEW source's loadedmetadata.
    store.playNow(sampleTrack('q', '/proxy/audio/q?itag=140&exp=1&sig=' + 'c'.repeat(32)));
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;

    // Old source is loaded and playing at call time.
    Object.defineProperty(audio, 'readyState', { value: 4, configurable: true });
    let seekTarget = 0;
    Object.defineProperty(audio, 'currentTime', {
      get: () => seekTarget,
      set: (v: number) => { seekTarget = v; },
      configurable: true,
    });

    playerControls.current!.restoreAt!(87);
    // The old fast-path bug would have set currentTime here already.
    expect(seekTarget).toBe(0);

    // Browser resource selection on src swap resets position, then new metadata.
    seekTarget = 0;
    audio.dispatchEvent(new Event('loadedmetadata'));
    expect(seekTarget).toBe(87);
  });

  it('restoreAt does not accumulate stale listeners across repeated calls', async () => {
    store.playNow(sampleTrack('q', '/proxy/audio/q?itag=140&exp=1&sig=' + 'c'.repeat(32)));
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    Object.defineProperty(audio, 'currentTime', { value: 0, writable: true, configurable: true });

    // Three switches before any metadata fires (each supersedes the last).
    playerControls.current!.restoreAt!(10);
    playerControls.current!.restoreAt!(20);
    playerControls.current!.restoreAt!(30);

    // Only the last-armed handler should run; if listeners accumulated, an
    // earlier handler would clobber currentTime afterward.
    audio.dispatchEvent(new Event('loadedmetadata'));
    expect(audio.currentTime).toBe(30);
  });

  it('"ended" event advances queue', async () => {
    store.enqueue(sampleTrack('a', '/proxy/audio/a?itag=140&exp=1&sig=' + '1'.repeat(32)));
    store.enqueue(sampleTrack('b', '/proxy/audio/b?itag=140&exp=1&sig=' + '2'.repeat(32)));
    store.playNow(sampleTrack('current', '/proxy/audio/c?itag=140&exp=1&sig=' + '3'.repeat(32)));
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    audio.dispatchEvent(new Event('ended'));
    await tick();
    expect(store.player.current?.videoId).toBe('a');
    expect(store.queue.map((t) => t.videoId)).toEqual(['b']);
  });
});

describe('Player — codec fallback', () => {
  beforeEach(() => {
    store.clear();
    store.player.current = null;
  });

  it('swaps to alternate codec format on <audio> error when _formats present', async () => {
    const opus: AudioFormat = { itag: 251, mime_type: 'audio/webm; codecs="opus"', bitrate: 160000, codec: 'opus', url: '/proxy/audio/abc?itag=251' };
    const aac: AudioFormat = { itag: 140, mime_type: 'audio/mp4; codecs="mp4a.40.2"', bitrate: 128000, codec: 'aac', url: '/proxy/audio/abc?itag=140', hls_url: '/api/hls/abc?itag=140' };

    store.player.current = {
      videoId: 'abc',
      title: 'T',
      author: 'A',
      durationSeconds: 100,
      thumbnailUrl: '',
      audioUrl: '/proxy/audio/abc?itag=251',
      itag: 251,
      qualityTier: 'hi',
      isLive: false,
      _formats: [opus, aac],
    };

    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    audio.dispatchEvent(new Event('error'));
    await tick();
    await tick();

    expect(store.player.current?.itag).toBe(140);
    expect(store.player.current?.audioUrl).toBe('/proxy/audio/abc?itag=140');
    // qualityTier preserved despite codec swap
    expect(store.player.current?.qualityTier).toBe('hi');
  });

  it('does NOT fall back when no alternate codec exists', async () => {
    const opus: AudioFormat = { itag: 251, mime_type: 'audio/webm; codecs="opus"', bitrate: 160000, codec: 'opus', url: '/proxy/audio/abc?itag=251' };

    store.player.current = {
      videoId: 'abc',
      title: 'T',
      author: 'A',
      durationSeconds: 100,
      thumbnailUrl: '',
      audioUrl: '/proxy/audio/abc?itag=251',
      itag: 251,
      qualityTier: 'hi',
      isLive: false,
      _formats: [opus],
    };

    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    audio.dispatchEvent(new Event('error'));
    await tick();

    // No codec to swap to. Pre-existing handleError path may fire (api.video refetch);
    // that's outside this test's scope. We only assert the itag did NOT flip silently.
    expect(store.player.current?.itag).toBe(251);
  });
});

describe('Player — live tracks', () => {
  beforeEach(() => {
    store.clear();
    store.player.current = null;
  });

  it('renders single <audio> element for live tracks (hls.js attaches via MSE)', async () => {
    // Live tracks render through the same <audio> element as VOD; hls.js
    // attaches asynchronously via MediaSource. We don't assert the src
    // attribute because hls.js sets it to a blob URL post-attach, and the
    // dynamic import is async — the in-test src will be empty at this point.
    store.player.current = {
      videoId: 'abc12345678', title: 'L', author: 'a', durationSeconds: 0,
      thumbnailUrl: '', audioUrl: '', itag: 0, isLive: true,
      liveStreamUrl: '/api/live/abc12345678/manifest.m3u8?exp=1&sig=x',
    } as any;
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    expect(audio).not.toBeNull();
    expect(container.querySelector('video')).toBeNull();
  });

  it('scrubber and restart button are absent when live', async () => {
    store.player.current = {
      videoId: 'abc12345678', title: 'L', author: 'a', durationSeconds: 0,
      thumbnailUrl: '', audioUrl: '', itag: 0, isLive: true,
      liveStreamUrl: '/api/live/abc12345678/manifest.m3u8',
    } as any;
    const { container } = render(Player);
    await tick();
    expect(container.querySelector('input[type="range"]')).toBeNull();
    expect(container.querySelector('[aria-label="Restart track"]')).toBeNull();
  });

  it('LIVE pill renders when track is live', async () => {
    store.player.current = {
      videoId: 'abc12345678', title: 'L', author: 'a', durationSeconds: 0,
      thumbnailUrl: '', audioUrl: '', itag: 0, isLive: true,
      liveStreamUrl: '/api/live/abc12345678/manifest.m3u8',
    } as any;
    const { findByText } = render(Player);
    expect(await findByText(/LIVE/i)).toBeInTheDocument();
  });
});

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

  it('airplayCapable is undefined when unsupported so NowPlaying can gate on it', async () => {
    // jsdom: no webkit API → airplaySupported stays false → flag must be falsy
    // (undefined), which NowPlaying uses to hide its button.
    store.playNow(sampleTrack('abc', '/proxy/audio/abc?itag=140&exp=1&sig=' + 'a'.repeat(32)));
    render(Player);
    await tick();
    expect(playerControls.current?.airplayCapable).toBeFalsy();
  });
});
