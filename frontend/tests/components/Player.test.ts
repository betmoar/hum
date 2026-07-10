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
