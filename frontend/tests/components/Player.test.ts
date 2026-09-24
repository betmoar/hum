import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import Player from '../../src/components/Player.svelte';
import { store, playerControls } from '../../src/lib/store.svelte';
import type { Track, AudioFormat } from '../../src/lib/types';
import { api, ApiError } from '../../src/lib/api';

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
  vi.restoreAllMocks();
  // handleError probes /health first; default to "Hum is up" so the existing
  // recovery-ladder tests exercise the ladder, not the unreachable path.
  vi.spyOn(api, 'health').mockResolvedValue();
  store.clear();
  store.history = [];
  store.dismissToast();
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

  it('scrubber is absent but previous is available when live', async () => {
    store.player.current = {
      videoId: 'abc12345678', title: 'L', author: 'a', durationSeconds: 0,
      thumbnailUrl: '', audioUrl: '', itag: 0, isLive: true,
      liveStreamUrl: '/api/live/abc12345678/manifest.m3u8',
    } as any;
    const { container } = render(Player);
    await tick();
    expect(container.querySelector('input[type="range"]')).toBeNull();
    // previous() goes back from live (to history), so the button stays.
    expect(container.querySelector('[aria-label="Previous track"]')).not.toBeNull();
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

  it('shows the airplay button and calls the picker when supported + available + non-live', async () => {
    const AVAIL = 'webkitplaybacktargetavailabilitychanged';
    const spy = vi.fn();
    (HTMLAudioElement.prototype as any).webkitShowPlaybackTargetPicker = spy;
    try {
      store.playNow(sampleTrack('abc', '/proxy/audio/abc?itag=140&exp=1&sig=' + 'a'.repeat(32)));
      const { container } = render(Player);
      await tick();
      // Button absent until an availability event says a target exists.
      let btn = container.querySelector('[aria-label="AirPlay"]');
      expect(btn).toBeNull();

      const audio = container.querySelector('audio')!;
      audio.dispatchEvent(new CustomEvent(AVAIL, { detail: { availability: 'available' } }));
      await tick();
      btn = container.querySelector('[aria-label="AirPlay"]');
      expect(btn).not.toBeNull();
      (btn as HTMLButtonElement).click();
      expect(spy).toHaveBeenCalled();
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

  it('airplayCapable stays false when unsupported so NowPlaying can gate on it', async () => {
    // jsdom: no webkit API → airplaySupported stays false → flag stays false.
    store.playNow(sampleTrack('abc', '/proxy/audio/abc?itag=140&exp=1&sig=' + 'a'.repeat(32)));
    render(Player);
    await tick();
    expect(store.player.airplayCapable).toBe(false);
  });
});


describe('Player — stub tracks (playlist enqueue)', () => {
  it('fetches a signed URL when a URL-less queued track becomes current', async () => {
    const { api } = await import('../../src/lib/api');
    const low = { itag: 139, mime_type: 'audio/mp4; codecs="mp4a.40.5"', bitrate: 48000, codec: 'aac',
      url: '/proxy/audio/stub1?itag=139&exp=1&sig=' + '5'.repeat(32) } as AudioFormat;
    const fmt = { itag: 140, mime_type: 'audio/mp4; codecs="mp4a.40.2"', bitrate: 128000, codec: 'aac',
      url: '/proxy/audio/stub1?itag=140&exp=1&sig=' + '4'.repeat(32) } as AudioFormat;
    // yt-dlp order: lowest first. A stub has no itag, so the tier decides.
    const spy = vi.spyOn(api, 'video').mockResolvedValue({ video_id: 'stub1', audio_formats: [low, fmt] } as never);
    store.enqueueStubs([{ videoId: 'stub1', title: 'S', author: 'A', durationSeconds: 10, thumbnailUrl: '' }]);
    store.playNow(store.queue[0]);
    const { container } = render(Player);
    await vi.waitFor(() => expect(spy).toHaveBeenCalledWith('stub1'));
    await vi.waitFor(() => expect((container.querySelector('audio') as HTMLAudioElement).src).toContain('/proxy/audio/stub1'));
    expect(store.player.current?.itag).not.toBe(139);
    spy.mockRestore();
  });
});

describe('Player — rehydrate writes back qualityTier (review finding #3)', () => {
  it('a stub with no itag/qualityTier gets qualityTier set to the fallback tier used', async () => {
    const { api } = await import('../../src/lib/api');
    const fmt = { itag: 140, mime_type: 'audio/mp4; codecs="mp4a.40.2"', bitrate: 128000, codec: 'aac',
      url: '/proxy/audio/stub2?itag=140&exp=1&sig=' + '4'.repeat(32) } as AudioFormat;
    const spy = vi.spyOn(api, 'video').mockResolvedValue({ video_id: 'stub2', audio_formats: [fmt] } as never);
    store.enqueueStubs([{ videoId: 'stub2', title: 'S', author: 'A', durationSeconds: 10, thumbnailUrl: '' }]);
    store.playNow(store.queue[0]);
    expect(store.player.current?.qualityTier).toBeUndefined();
    render(Player);
    await vi.waitFor(() => expect(spy).toHaveBeenCalledWith('stub2'));
    await vi.waitFor(() => expect(store.player.current?.qualityTier).toBe(store.settings.defaultQuality));
    spy.mockRestore();
  });
});

describe('Player — rehydrate skips unplayable tracks (review finding #4)', () => {
  it('advances to the next queued track when the rehydrate fetch rejects', async () => {
    const { api } = await import('../../src/lib/api');
    const spy = vi.spyOn(api, 'video').mockImplementation((id: string) => {
      if (id === 'bad') return Promise.reject(new Error('gone'));
      return Promise.resolve({
        video_id: 'b', title: 'B', author: 'A', duration_seconds: 10, thumbnail_url: '',
        audio_formats: [{ itag: 140, mime_type: 'audio/mp4; codecs="mp4a.40.2"', bitrate: 128000, codec: 'aac', url: '/proxy/audio/b?itag=140' }],
      } as never);
    });
    store.enqueueStubs([{ videoId: 'b', title: 'B', author: 'A', durationSeconds: 10, thumbnailUrl: '' }]);
    store.playNow({ videoId: 'bad', title: 'Bad', author: 'A', durationSeconds: 10, thumbnailUrl: '', audioUrl: '', itag: 0 });
    render(Player);
    await vi.waitFor(() => expect(store.player.current?.videoId).toBe('b'));
    spy.mockRestore();
  });
});

describe('Player — live stub tracks', () => {
  it('turns a URL-less stub into a live track when the video is live', async () => {
    const { api } = await import('../../src/lib/api');
    const spy = vi.spyOn(api, 'video').mockResolvedValue({
      video_id: 'live1', is_live: true, audio_formats: [], title: 'Radio', author: 'A',
      duration_seconds: 0, thumbnail_url: '', live_stream_url: '/api/live/live1/manifest.m3u8?exp=1&sig=x',
    } as never);
    store.enqueueStubs([{ videoId: 'live1', title: 'Radio', author: 'A', durationSeconds: 0, thumbnailUrl: '' }]);
    store.playNow(store.queue[0]);
    render(Player);
    await vi.waitFor(() => expect(store.player.current?.isLive).toBe(true));
    expect(store.player.current?.liveStreamUrl).toContain('/api/live/live1/manifest.m3u8');
    spy.mockRestore();
  });
});

describe('Player — resume, previous, media session, unreachable', () => {
  it('does not autoplay a restored (isPlaying=false) track', async () => {
    store.player.current = sampleTrack('r', '/proxy/audio/r?x');
    store.player.isPlaying = false;
    const { container } = render(Player);
    await tick();
    expect((container.querySelector('audio') as HTMLAudioElement).autoplay).toBe(false);
  });

  it('autoplays a track started with playNow', async () => {
    store.playNow(sampleTrack('p', '/proxy/audio/p?x'));
    const { container } = render(Player);
    await tick();
    expect((container.querySelector('audio') as HTMLAudioElement).autoplay).toBe(true);
  });

  it('seeks to startPositionFor once metadata loads', async () => {
    vi.spyOn(store, 'startPositionFor').mockReturnValue(123);
    store.playNow(sampleTrack('s', '/proxy/audio/s?x'));
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    Object.defineProperty(audio, 'currentTime', { value: 0, writable: true });
    audio.dispatchEvent(new Event('loadedmetadata'));
    expect(audio.currentTime).toBe(123);
  });

  it('a same-video object swap (quality switch) does not re-arm the start seek', async () => {
    const spy = vi.spyOn(store, 'startPositionFor').mockReturnValue(0);
    store.playNow(sampleTrack('w', '/proxy/audio/w?itag=140'));
    render(Player);
    await tick();
    store.player.current = { ...store.player.current!, audioUrl: '/proxy/audio/w?itag=251', itag: 251 };
    await tick();
    store.setPosition(30);
    await tick();
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('pause records position in the store', async () => {
    store.playNow(sampleTrack('q', '/proxy/audio/q?x'));
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    audio.dispatchEvent(new Event('loadedmetadata'));
    Object.defineProperty(audio, 'currentTime', { value: 55, writable: true });
    audio.dispatchEvent(new Event('pause'));
    expect(store.player.positionSeconds).toBe(55);
    expect(store.player.isPlaying).toBe(false);
  });

  it('pause of a long vod writes a bookmark', async () => {
    store.playNow({ ...sampleTrack('long', '/proxy/audio/long?x'), durationSeconds: 1200 });
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    Object.defineProperty(audio, 'currentTime', { value: 300, writable: true });
    Object.defineProperty(audio, 'duration', { value: 1200, configurable: true });
    audio.dispatchEvent(new Event('loadedmetadata'));
    audio.dispatchEvent(new Event('pause'));
    expect(JSON.parse(localStorage.getItem('hum.bookmarks')!).long.pos).toBe(300);
  });

  it('pause before the new source loads does not save (track-switch guard)', async () => {
    store.playNow(sampleTrack('g', '/proxy/audio/g?x'));
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    audio.dispatchEvent(new Event('loadedmetadata'));
    audio.dispatchEvent(new Event('emptied'));
    Object.defineProperty(audio, 'currentTime', { value: 99, writable: true });
    audio.dispatchEvent(new Event('pause'));
    expect(store.player.positionSeconds).toBe(0);
  });

  it('ended clears the bookmark and advances', async () => {
    localStorage.setItem('hum.bookmarks', JSON.stringify({ e: { pos: 300, at: 1 } }));
    const next = vi.spyOn(store, 'next');
    store.playNow({ ...sampleTrack('e', '/proxy/audio/e?x'), durationSeconds: 1200 });
    const { container } = render(Player);
    await tick();
    container.querySelector('audio')!.dispatchEvent(new Event('ended'));
    expect(JSON.parse(localStorage.getItem('hum.bookmarks')!).e).toBeUndefined();
    expect(next).toHaveBeenCalled();
  });

  it('previous button calls store.previous', async () => {
    const spy = vi.spyOn(store, 'previous');
    store.playNow(sampleTrack('p', '/proxy/audio/p?x'));
    const { getByLabelText } = render(Player);
    await tick();
    getByLabelText('Previous track').click();
    expect(spy).toHaveBeenCalled();
  });

  it('playerControls.seekTo sets currentTime', async () => {
    store.playNow(sampleTrack('k', '/proxy/audio/k?x'));
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    Object.defineProperty(audio, 'currentTime', { value: 50, writable: true });
    playerControls.current!.seekTo!(0);
    expect(audio.currentTime).toBe(0);
  });

  it('registers seek handlers and position state for vod', async () => {
    const handlers: Record<string, any> = {};
    const setPositionState = vi.fn();
    (navigator as any).mediaSession = {
      metadata: null,
      setActionHandler: (k: string, f: any) => { handlers[k] = f; },
      setPositionState,
    };
    (globalThis as any).MediaMetadata = class { constructor(public o: any) {} };
    try {
      store.playNow(sampleTrack('m', '/proxy/audio/m?x'));
      const { container } = render(Player);
      await tick();
      expect(typeof handlers.seekto).toBe('function');
      expect(typeof handlers.seekbackward).toBe('function');
      expect(typeof handlers.seekforward).toBe('function');
      const audio = container.querySelector('audio') as HTMLAudioElement;
      Object.defineProperty(audio, 'duration', { value: 200, configurable: true });
      Object.defineProperty(audio, 'currentTime', { value: 10, writable: true });
      audio.dispatchEvent(new Event('loadedmetadata'));
      expect(setPositionState).toHaveBeenCalledWith(expect.objectContaining({ duration: 200, position: 10 }));
      handlers.seekto({ seekTime: 42 });
      expect(audio.currentTime).toBe(42);
      handlers.seekbackward({});
      expect(audio.currentTime).toBe(32);
    } finally {
      delete (navigator as any).mediaSession;
    }
  });

  it('clears seek handlers for live', async () => {
    const handlers: Record<string, any> = {};
    (navigator as any).mediaSession = {
      metadata: null,
      setActionHandler: (k: string, f: any) => { handlers[k] = f; },
      setPositionState: vi.fn(),
    };
    (globalThis as any).MediaMetadata = class { constructor(public o: any) {} };
    try {
      store.player.current = {
        videoId: 'live1', title: 'L', author: 'a', durationSeconds: 0,
        thumbnailUrl: '', audioUrl: '', itag: 0, isLive: true,
        liveStreamUrl: '/api/live/live1/manifest.m3u8?exp=1&sig=x',
      };
      render(Player);
      await tick();
      expect(handlers.seekto).toBeNull();
    } finally {
      delete (navigator as any).mediaSession;
    }
  });

  it('unreachable server: shows Hum toast and does not refetch', async () => {
    vi.spyOn(api, 'health').mockRejectedValue(new ApiError(0, 'x'));
    const video = vi.spyOn(api, 'video');
    store.playNow(sampleTrack('u', '/proxy/audio/u?x'));
    const { container } = render(Player);
    await tick();
    container.querySelector('audio')!.dispatchEvent(new Event('error'));
    await new Promise((r) => setTimeout(r, 0));
    await tick();
    expect(store.toast?.message).toBe("Can't reach Hum server.");
    expect(store.toast?.action?.label).toBe('Retry');
    expect(video).not.toHaveBeenCalled();
  });
});

describe('Player — review fixes', () => {
  it('codec-fallback recovery at position 0 keeps the pending start seek', async () => {
    vi.spyOn(store, 'startPositionFor').mockReturnValue(1200);
    const opus: AudioFormat = { itag: 251, mime_type: 'audio/webm; codecs="opus"', bitrate: 160000, codec: 'opus', url: '/proxy/audio/cf?itag=251' };
    const aac: AudioFormat = { itag: 140, mime_type: 'audio/mp4; codecs="mp4a.40.2"', bitrate: 128000, codec: 'mp4a.40.2', url: '/proxy/audio/cf?itag=140' };
    store.playNow({
      videoId: 'cf', title: 'T', author: 'A', durationSeconds: 7200, thumbnailUrl: '',
      audioUrl: opus.url, itag: 251, qualityTier: 'hi', isLive: false, _formats: [opus, aac],
    });
    const { container } = render(Player);
    await tick();
    const audio = container.querySelector('audio') as HTMLAudioElement;
    audio.dispatchEvent(new Event('error'));
    await new Promise((r) => setTimeout(r, 0));
    await tick();
    expect(store.player.current?.itag).toBe(140);
    let seek = -1;
    Object.defineProperty(audio, 'currentTime', { get: () => seek, set: (v: number) => { seek = v; }, configurable: true });
    audio.dispatchEvent(new Event('loadedmetadata'));
    expect(seek).toBe(1200);
  });

  it('handleError does not clobber a track picked during the health probe', async () => {
    let release!: () => void;
    vi.spyOn(api, 'health').mockReturnValue(new Promise<void>((r) => { release = r; }));
    const opus: AudioFormat = { itag: 251, mime_type: 'audio/webm; codecs="opus"', bitrate: 160000, codec: 'opus', url: '/proxy/audio/r1?itag=251' };
    const aac: AudioFormat = { itag: 140, mime_type: 'audio/mp4; codecs="mp4a.40.2"', bitrate: 128000, codec: 'mp4a.40.2', url: '/proxy/audio/r1?itag=140' };
    store.playNow({
      videoId: 'r1', title: 'A', author: 'A', durationSeconds: 100, thumbnailUrl: '',
      audioUrl: opus.url, itag: 251, isLive: false, _formats: [opus, aac],
    });
    const { container } = render(Player);
    await tick();
    container.querySelector('audio')!.dispatchEvent(new Event('error'));
    store.playNow(sampleTrack('r2', '/proxy/audio/r2?x'));
    release();
    await new Promise((r) => setTimeout(r, 0));
    await tick();
    expect(store.player.current?.videoId).toBe('r2');
  });

  it('Next button keeps the bookmark (only ended clears it)', async () => {
    localStorage.setItem('hum.bookmarks', JSON.stringify({ nb: { pos: 300, at: 1 } }));
    store.playNow({ ...sampleTrack('nb', '/proxy/audio/nb?x'), durationSeconds: 1200 });
    const { getByLabelText } = render(Player);
    await tick();
    getByLabelText('Next track').click();
    expect(JSON.parse(localStorage.getItem('hum.bookmarks')!).nb.pos).toBe(300);
  });

  it('switching to a new track while playing calls play() explicitly', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    store.playNow(sampleTrack('s1', '/proxy/audio/s1?x'));
    render(Player);
    await tick();
    play.mockClear();
    store.playNow(sampleTrack('s2', '/proxy/audio/s2?x'));
    await tick();
    expect(play).toHaveBeenCalled();
  });

  it('a restored (paused) track is not played on mount', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    store.player.current = sampleTrack('rp', '/proxy/audio/rp?x');
    store.player.isPlaying = false;
    render(Player);
    await tick();
    expect(play).not.toHaveBeenCalled();
  });
});

describe('Player — pre-existing fixes', () => {
  it('ended under repeat one rewinds the element and plays again', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    store.playNow(sampleTrack('r1', '/proxy/audio/r1?x'));
    store.player.repeat = 'one';
    try {
      const { container } = render(Player);
      await tick();
      const audio = container.querySelector('audio') as HTMLAudioElement;
      let ct = 100;
      Object.defineProperty(audio, 'currentTime', { get: () => ct, set: (v: number) => { ct = v; }, configurable: true });
      play.mockClear();
      audio.dispatchEvent(new Event('ended'));
      await tick();
      expect(ct).toBe(0);
      expect(play).toHaveBeenCalled();
    } finally {
      store.player.repeat = 'off';
    }
  });

  it('rehydrate refetch restores _formats and a consistent itag', async () => {
    const f251: AudioFormat = { itag: 251, mime_type: 'audio/webm; codecs="opus"', bitrate: 160000, codec: 'opus', url: '/proxy/audio/rh?itag=251' };
    const f140: AudioFormat = { itag: 140, mime_type: 'audio/mp4; codecs="mp4a.40.2"', bitrate: 128000, codec: 'mp4a.40.2', url: '/proxy/audio/rh?itag=140' };
    vi.spyOn(api, 'video').mockResolvedValue({
      video_id: 'rh', title: 'T', author: 'A', channel_id: 'c', duration_seconds: 100,
      thumbnail_url: '', audio_formats: [f251, f140], video_formats: [],
    });
    // Restored track: URL stripped, and its old itag (18) no longer offered.
    store.player.current = { ...sampleTrack('rh', ''), itag: 18 };
    store.player.isPlaying = false;
    render(Player);
    await new Promise((r) => setTimeout(r, 0));
    await tick();
    const cur = store.player.current!;
    expect(cur.audioUrl).toBe(f251.url);
    expect(cur.itag).toBe(251);
    expect(cur.bitrate).toBe(160000);
    expect(cur._formats?.map((f) => f.itag)).toEqual([251, 140]);
  });
});
