import { describe, it, expect, beforeEach } from 'vitest';
import { vi } from 'vitest';
import type { Track } from '../../src/lib/types';

const t = (id: string): Track => ({
  videoId: id,
  title: `Track ${id}`,
  author: 'A',
  durationSeconds: 100,
  thumbnailUrl: '',
  audioUrl: `/proxy/audio/${id}`,
  itag: 140,
});

// Helper to get a fresh store instance per test by re-importing. Some tests
// in this file call vi.resetModules() (see the rehydrate tests below), which
// makes this dynamic import return a NEW module instance — with its own
// `playerControls` singleton, distinct from the one bound by any static
// top-of-file import. Callers that need `playerControls` for the currently
// active store MUST get it from this same import, not a static import.
async function freshStore() {
  const mod = await import('../../src/lib/store.svelte');
  mod.store.clear();
  mod.store.invalidateToken();
  mod.store.settings.defaultQuality = 'hi';
  mod.store.settings.musicOnly = true;
  // Reset player state so tests don't bleed into each other via the singleton.
  mod.store.player.current = null;
  mod.store.player.isPlaying = false;
  mod.store.player.positionSeconds = 0;
  mod.store.player.shuffle = false;
  mod.store.player.repeat = 'off';
  mod.store.player.isExpanded = false;
  mod.store.history = [];
  return mod.store;
}

beforeEach(() => {
  localStorage.clear();
});

describe('AppStore', () => {
  it('starts with empty queue and null token', async () => {
    const s = await freshStore();
    expect(s.queue).toEqual([]);
    expect(s.settings.bearerToken).toBeNull();
    expect(s.player.current).toBeNull();
  });

  it('setToken persists to localStorage', async () => {
    const s = await freshStore();
    s.setToken('abc');
    expect(s.settings.bearerToken).toBe('abc');
    await new Promise((r) => setTimeout(r, 250));
    expect(localStorage.getItem('hum.bearer')).toBe('abc');
  });

  it('invalidateToken clears localStorage', async () => {
    const s = await freshStore();
    s.setToken('abc');
    await new Promise((r) => setTimeout(r, 250));
    s.invalidateToken();
    await new Promise((r) => setTimeout(r, 250));
    expect(s.settings.bearerToken).toBeNull();
    expect(localStorage.getItem('hum.bearer')).toBeNull();
  });

  it('enqueue appends', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    s.enqueue(t('b'));
    expect(s.queue.map((x) => x.videoId)).toEqual(['a', 'b']);
  });

  it('playNow sets current without altering queue', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    s.playNow(t('b'));
    expect(s.player.current?.videoId).toBe('b');
    expect(s.player.isPlaying).toBe(true);
    expect(s.queue.map((x) => x.videoId)).toEqual(['a']);
  });

  it('next pops from queue into current', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    s.enqueue(t('b'));
    s.next();
    expect(s.player.current?.videoId).toBe('a');
    expect(s.queue.map((x) => x.videoId)).toEqual(['b']);
  });

  it('next on empty queue clears current', async () => {
    const s = await freshStore();
    s.playNow(t('a'));
    s.next();
    expect(s.player.current).toBeNull();
    expect(s.player.isPlaying).toBe(false);
  });

  it('remove by index', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    s.enqueue(t('b'));
    s.enqueue(t('c'));
    s.remove(1);
    expect(s.queue.map((x) => x.videoId)).toEqual(['a', 'c']);
  });

  it('reorder moves item', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    s.enqueue(t('b'));
    s.enqueue(t('c'));
    s.reorder(0, 2);
    expect(s.queue.map((x) => x.videoId)).toEqual(['b', 'c', 'a']);
  });

  it('clear empties queue', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    s.clear();
    expect(s.queue).toEqual([]);
  });

  it('playNext prepends to queue', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    s.enqueue(t('b'));
    s.playNext(t('z'));
    expect(s.queue.map((x) => x.videoId)).toEqual(['z', 'a', 'b']);
  });

  it('enqueueStubs appends by default', async () => {
    const s = await freshStore();
    s.enqueue(t('x'));
    s.enqueueStubs([
      { videoId: 'a', title: 'A', author: '', durationSeconds: 1, thumbnailUrl: '' },
      { videoId: 'b', title: 'B', author: '', durationSeconds: 1, thumbnailUrl: '' },
    ]);
    expect(s.queue.map((q) => q.videoId)).toEqual(['x', 'a', 'b']);
  });

  it('enqueueStubs({ next: true }) inserts at the front of the queue, in order', async () => {
    const s = await freshStore();
    s.enqueue(t('x'));
    s.enqueue(t('y'));
    s.enqueueStubs(
      [
        { videoId: 'b', title: 'B', author: '', durationSeconds: 1, thumbnailUrl: '' },
        { videoId: 'c', title: 'C', author: '', durationSeconds: 1, thumbnailUrl: '' },
      ],
      { next: true },
    );
    expect(s.queue.map((q) => q.videoId)).toEqual(['b', 'c', 'x', 'y']);
  });

  it('enqueue assigns a stable queueId to each track', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    s.enqueue(t('a')); // same videoId enqueued twice — exactly what queueId disambiguates
    const ids = s.queue.map((x) => x.queueId);
    expect(ids[0]).toBeTruthy();
    expect(ids[1]).toBeTruthy();
    expect(ids[0]).not.toBe(ids[1]);
  });

  it('playNext assigns a queueId', async () => {
    const s = await freshStore();
    s.playNext(t('z'));
    expect(s.queue[0].queueId).toBeTruthy();
  });

  it('reorder preserves each track\'s queueId (not just position)', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    s.enqueue(t('b'));
    s.enqueue(t('c'));
    const idsBefore = s.queue.map((x) => x.queueId);
    s.reorder(0, 2);
    const idsAfter = s.queue.map((x) => x.queueId);
    expect(idsAfter).toEqual([idsBefore[1], idsBefore[2], idsBefore[0]]);
  });

  it('queueId survives persistence and rehydrate (not stripped)', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    const idBefore = s.queue[0].queueId;
    await new Promise((r) => setTimeout(r, 250));
    const raw = localStorage.getItem('hum.queue');
    const parsed = JSON.parse(raw!);
    expect(parsed[0].queueId).toBe(idBefore);
  });

  it('toggleShuffle flips shuffle', async () => {
    const s = await freshStore();
    expect(s.player.shuffle).toBe(false);
    s.toggleShuffle();
    expect(s.player.shuffle).toBe(true);
  });

  it('cycleRepeat cycles off -> all -> one -> off', async () => {
    const s = await freshStore();
    expect(s.player.repeat).toBe('off');
    s.cycleRepeat(); expect(s.player.repeat).toBe('all');
    s.cycleRepeat(); expect(s.player.repeat).toBe('one');
    s.cycleRepeat(); expect(s.player.repeat).toBe('off');
  });

  it('next with repeat=all wraps current to end', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    s.playNow(t('current'));
    s.player.repeat = 'all';
    s.next();
    expect(s.player.current?.videoId).toBe('a');
    expect(s.queue.map((x) => x.videoId)).toEqual(['current']);
  });

  it('notify sets toast', async () => {
    const s = await freshStore();
    s.notify('hello');
    expect(s.toast?.message).toBe('hello');
    expect(s.toast?.kind).toBe('info');
  });

  it('dismissToast clears toast', async () => {
    const s = await freshStore();
    s.notify('hello');
    s.dismissToast();
    expect(s.toast).toBeNull();
  });

  it('queue persists across reload', async () => {
    const s = await freshStore();
    s.enqueue(t('a'));
    s.enqueue(t('b'));
    await new Promise((r) => setTimeout(r, 250));
    const raw = localStorage.getItem('hum.queue');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.map((x: Track) => x.videoId)).toEqual(['a', 'b']);
  });

  it('flush strips audioUrl from persisted queue', async () => {
    // The store always writes empty audioUrl to localStorage, since the
    // signed URL has a 6h TTL and is almost always stale on next load.
    const s = await freshStore();
    s.enqueue({
      videoId: 'def', title: 't', author: 'a', durationSeconds: 100,
      thumbnailUrl: '', audioUrl: '/proxy/audio/def?sig=fresh', itag: 140,
    });
    await new Promise((r) => setTimeout(r, 250));
    const raw = localStorage.getItem('hum.queue');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    for (const track of parsed) {
      expect(track.audioUrl).toBe('');
    }
  });

  it('flush strips hlsUrl from persisted queue', async () => {
    // hlsUrl is signed like audioUrl. If it survives persistence, Safari's
    // pickVodSrc() returns the stale URL on rehydrate and the refetch effect
    // never runs — playback dies with an expired-signature error.
    const s = await freshStore();
    s.enqueue({
      videoId: 'hls', title: 't', author: 'a', durationSeconds: 100,
      thumbnailUrl: '', audioUrl: '/proxy/audio/hls?sig=fresh', itag: 140,
      hlsUrl: '/api/hls/hls.m3u8?sig=fresh',
    });
    await new Promise((r) => setTimeout(r, 250));
    const parsed = JSON.parse(localStorage.getItem('hum.queue')!);
    for (const track of parsed) {
      expect(track.hlsUrl).toBeUndefined();
    }
  });

  it('expandPlayer sets isExpanded only if a track is current', async () => {
    const s = await freshStore();
    s.expandPlayer();
    expect(s.player.isExpanded).toBe(false); // no current track — no expand
    s.playNow(t('a'));
    s.expandPlayer();
    expect(s.player.isExpanded).toBe(true);
  });

  it('collapsePlayer clears isExpanded', async () => {
    const s = await freshStore();
    s.playNow(t('a'));
    s.expandPlayer();
    s.collapsePlayer();
    expect(s.player.isExpanded).toBe(false);
  });

  it('togglePlayerExpanded flips state', async () => {
    const s = await freshStore();
    s.playNow(t('a'));
    s.togglePlayerExpanded();
    expect(s.player.isExpanded).toBe(true);
    s.togglePlayerExpanded();
    expect(s.player.isExpanded).toBe(false);
  });

  it('rehydrate strips audioUrl from previously-persisted queue', async () => {
    // Seed localStorage BEFORE the AppStore module is loaded for the first
    // time. Use vi.resetModules() so the dynamic import below constructs a
    // fresh AppStore that actually reads our seed.
    vi.resetModules();
    localStorage.setItem(
      'hum.queue',
      JSON.stringify([
        {
          videoId: 'rehydrate-test', title: 't', author: 'a', durationSeconds: 100,
          thumbnailUrl: '', audioUrl: '/proxy/audio/rehydrate-test?sig=stale-from-disk', itag: 140,
        },
      ]),
    );
    const mod = await import('../../src/lib/store.svelte');
    expect(mod.store.queue.map((t) => t.videoId)).toEqual(['rehydrate-test']);
    expect(mod.store.queue[0].audioUrl).toBe('');
  });

  it('rehydrate strips hlsUrl from previously-persisted queue', async () => {
    // Defense in depth for queues written by older builds that persisted
    // hlsUrl: the load path must clear it even if the flush path missed it.
    vi.resetModules();
    localStorage.setItem(
      'hum.queue',
      JSON.stringify([
        {
          videoId: 'rehydrate-hls', title: 't', author: 'a', durationSeconds: 100,
          thumbnailUrl: '', audioUrl: '', itag: 140,
          hlsUrl: '/api/hls/rehydrate-hls.m3u8?sig=stale-from-disk',
        },
      ]),
    );
    const mod = await import('../../src/lib/store.svelte');
    expect(mod.store.queue[0].hlsUrl).toBeUndefined();
  });
});

describe('AppStore — settings', () => {
  it('settings.defaultQuality defaults to "hi"', async () => {
    const s = await freshStore();
    expect(s.settings.defaultQuality).toBe('hi');
  });

  it('settings.musicOnly defaults to true', async () => {
    const s = await freshStore();
    expect(s.settings.musicOnly).toBe(true);
  });

  it('setDefaultQuality persists to localStorage', async () => {
    const s = await freshStore();
    s.setDefaultQuality('low');
    expect(s.settings.defaultQuality).toBe('low');
    await new Promise((r) => setTimeout(r, 250));
    expect(localStorage.getItem('hum.defaultQuality')).toBe('low');
  });

  it('setMusicOnly persists to localStorage', async () => {
    const s = await freshStore();
    s.setMusicOnly(false);
    expect(s.settings.musicOnly).toBe(false);
    await new Promise((r) => setTimeout(r, 250));
    expect(localStorage.getItem('hum.musicOnly')).toBe('false');
  });
});

describe('AppStore — by-id helpers', () => {
  it('playNowById fetches details and plays at defaultQuality', async () => {
    const s = await freshStore();
    s.setToken('t');
    const fakeDetails = {
      video_id: 'abc', title: 'T', author: 'A', channel_id: 'c',
      duration_seconds: 100, thumbnail_url: 'thumb', audio_formats: [
        { itag: 251, mime_type: 'audio/webm; codecs="opus"', bitrate: 160000, codec: 'opus', url: '/proxy/audio/abc?itag=251' }
      ], video_formats: [],
    };
    const apiMod = await import('../../src/lib/api');
    vi.spyOn(apiMod.api, 'video').mockResolvedValue(fakeDetails as any);

    await s.playNowById('abc');
    expect(s.player.current?.videoId).toBe('abc');
    expect(s.player.current?.qualityTier).toBe('hi');
  });

  it('enqueueById appends to queue', async () => {
    const s = await freshStore();
    s.setToken('t');
    const fakeDetails = {
      video_id: 'abc', title: 'T', author: 'A', channel_id: 'c',
      duration_seconds: 100, thumbnail_url: 'thumb', audio_formats: [
        { itag: 251, mime_type: 'audio/webm; codecs="opus"', bitrate: 160000, codec: 'opus', url: '/proxy/audio/abc?itag=251' }
      ], video_formats: [],
    };
    const apiMod = await import('../../src/lib/api');
    vi.spyOn(apiMod.api, 'video').mockResolvedValue(fakeDetails as any);

    await s.enqueueById('abc');
    expect(s.queue).toHaveLength(1);
    expect(s.queue[0].videoId).toBe('abc');
  });
});

describe('AppStore.switchQuality', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('refetches and updates audioUrl/itag/qualityTier on tier change', async () => {
    const s = await freshStore();
    s.setToken('t');
    s.player.current = {
      videoId: 'abc', title: 'T', author: 'A', durationSeconds: 100,
      thumbnailUrl: '', audioUrl: '/proxy/audio/abc?itag=251', itag: 251,
      qualityTier: 'hi', isLive: false,
    } as any;

    const fakeDetails = {
      video_id: 'abc', title: 'T', author: 'A', channel_id: 'c',
      duration_seconds: 100, thumbnail_url: '',
      audio_formats: [
        { itag: 251, mime_type: 'audio/webm; codecs="opus"', bitrate: 160000, codec: 'opus', url: '/proxy/audio/abc?itag=251' },
        { itag: 249, mime_type: 'audio/webm; codecs="opus"', bitrate: 50000, codec: 'opus', url: '/proxy/audio/abc?itag=249' },
      ],
      video_formats: [],
    };
    const apiMod = await import('../../src/lib/api');
    vi.spyOn(apiMod.api, 'video').mockResolvedValue(fakeDetails as any);

    await s.switchQuality('low');
    expect(s.player.current?.qualityTier).toBe('low');
    expect(s.player.current?.itag).toBe(249);
  });

  it('is a no-op when tier matches current track', async () => {
    const s = await freshStore();
    s.setToken('t');
    s.player.current = {
      videoId: 'abc', title: 'T', author: 'A', durationSeconds: 100,
      thumbnailUrl: '', audioUrl: '/x', itag: 251,
      qualityTier: 'hi', isLive: false,
    } as any;
    const apiMod = await import('../../src/lib/api');
    const spy = vi.spyOn(apiMod.api, 'video');
    await s.switchQuality('hi');
    expect(spy).not.toHaveBeenCalled();
  });

  it('calls playerControls.restoreAt with the captured position instead of touching the DOM', async () => {
    // NOTE: playerControls must come from the SAME dynamic module instance as
    // `s` (see freshStore() comment) — the rehydrate tests above call
    // vi.resetModules(), so the static top-of-file `playerControls` import
    // may be bound to a stale module instance whose `switchQuality` never
    // observes writes to it.
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    const pc = mod.playerControls;
    s.setToken('t');
    s.player.current = {
      videoId: 'abc', title: 'T', author: 'A', durationSeconds: 100,
      thumbnailUrl: '', audioUrl: '/proxy/audio/abc?itag=251', itag: 251,
      qualityTier: 'hi', isLive: false,
    } as any;

    const restoreAt = vi.fn();
    const getPosition = vi.fn(() => 37);
    pc.current = {
      play: () => {}, pause: () => {}, toggle: () => {},
      seekBy: () => {}, setVolume: () => {}, toggleMute: () => {},
      getPosition, restoreAt,
    };

    const fakeDetails = {
      video_id: 'abc', title: 'T', author: 'A', channel_id: 'c',
      duration_seconds: 100, thumbnail_url: '',
      audio_formats: [
        { itag: 251, mime_type: 'audio/webm; codecs="opus"', bitrate: 160000, codec: 'opus', url: '/proxy/audio/abc?itag=251' },
        { itag: 249, mime_type: 'audio/webm; codecs="opus"', bitrate: 50000, codec: 'opus', url: '/proxy/audio/abc?itag=249' },
      ],
      video_formats: [],
    };
    const apiMod = await import('../../src/lib/api');
    vi.spyOn(apiMod.api, 'video').mockResolvedValue(fakeDetails as any);

    await s.switchQuality('low');

    expect(getPosition).toHaveBeenCalled();
    expect(restoreAt).toHaveBeenCalledWith(37);

    pc.current = null;
  });
});

describe('AppStore — live tracks', () => {
  it('#buildTrack produces a live Track when d.is_live=true', async () => {
    const s = await freshStore();
    s.setToken('t');
    const fakeDetails = {
      video_id: 'abc12345678', title: 'Lofi Radio', author: 'ChilledCow',
      channel_id: 'UC1', duration_seconds: 0, thumbnail_url: 'thumb',
      audio_formats: [], video_formats: [],
      is_live: true,
      live_stream_url: '/api/live/abc12345678/manifest.m3u8?exp=999&sig=ab',
    };
    const apiMod = await import('../../src/lib/api');
    vi.spyOn(apiMod.api, 'video').mockResolvedValue(fakeDetails as any);

    const envMod = await import('../../src/lib/browserEnv');
    envMod._resetAudioEnvForTests();
    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('probably');

    await s.playNowById('abc12345678');
    expect(s.player.current?.isLive).toBe(true);
    expect(s.player.current?.liveStreamUrl).toBe(fakeDetails.live_stream_url);
    expect(s.player.current?.audioUrl).toBe('');
  });

  it('playNowById accepts live tracks regardless of browser (hls.js)', async () => {
    const s = await freshStore();
    s.setToken('t');
    const fakeDetails = {
      video_id: 'abc12345678', title: 'Lofi Radio', author: 'ChilledCow',
      channel_id: 'UC1', duration_seconds: 0, thumbnail_url: 'thumb',
      audio_formats: [], video_formats: [],
      is_live: true,
      live_stream_url: '/api/live/abc12345678/manifest.m3u8?exp=999&sig=ab',
    };
    const apiMod = await import('../../src/lib/api');
    vi.spyOn(apiMod.api, 'video').mockResolvedValue(fakeDetails as any);

    // Non-Safari env (no native HLS) — used to refuse, now should accept
    // because hls.js handles playback in the Player component.
    const envMod = await import('../../src/lib/browserEnv');
    envMod._resetAudioEnvForTests();
    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('');

    await s.playNowById('abc12345678');
    expect(s.player.current?.isLive).toBe(true);
    expect(s.player.current?.liveStreamUrl).toBe(fakeDetails.live_stream_url);
  });

  it('enqueueById accepts live tracks regardless of browser (hls.js)', async () => {
    const s = await freshStore();
    s.setToken('t');
    const fakeDetails = {
      video_id: 'abc12345678', title: 'Lofi', author: 'a',
      channel_id: 'c', duration_seconds: 0, thumbnail_url: '',
      audio_formats: [], video_formats: [],
      is_live: true, live_stream_url: '/api/live/abc12345678/manifest.m3u8',
    };
    const apiMod = await import('../../src/lib/api');
    vi.spyOn(apiMod.api, 'video').mockResolvedValue(fakeDetails as any);

    const envMod = await import('../../src/lib/browserEnv');
    envMod._resetAudioEnvForTests();
    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('');

    await s.enqueueById('abc12345678');
    expect(s.queue).toHaveLength(1);
    expect(s.queue[0].isLive).toBe(true);
  });

  it('#flush strips liveStreamUrl from persisted queue items', async () => {
    const s = await freshStore();
    s.queue = [{
      videoId: 'abc12345678', title: 'L', author: 'a', durationSeconds: 0,
      thumbnailUrl: '', audioUrl: '', itag: 0, isLive: true,
      liveStreamUrl: '/api/live/abc12345678/manifest.m3u8?exp=1&sig=x',
    } as any];
    await new Promise((r) => setTimeout(r, 250));
    const raw = localStorage.getItem('hum.queue');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed[0].liveStreamUrl).toBeUndefined();
  });
});

describe('history + previous', () => {
  it('next pushes outgoing current to history', async () => {
    const s = await freshStore();
    s.playNow(t('a'));
    s.enqueue(t('b'));
    s.next();
    expect(s.history.map((x) => x.videoId)).toEqual(['a']);
  });

  it('next with empty queue and repeat off pushes the stopped track', async () => {
    const s = await freshStore();
    s.playNow(t('a'));
    s.next();
    expect(s.player.current).toBeNull();
    expect(s.history.map((x) => x.videoId)).toEqual(['a']);
  });

  it('repeat one does not push', async () => {
    const s = await freshStore();
    s.playNow(t('a'));
    s.player.repeat = 'one';
    s.next();
    expect(s.history).toEqual([]);
  });

  it('repeat all wrap of a lone track does not push', async () => {
    const s = await freshStore();
    s.playNow(t('a'));
    s.player.repeat = 'all';
    s.next();
    expect(s.history).toEqual([]);
  });

  it('playNow of a different track pushes; same track does not', async () => {
    const s = await freshStore();
    s.playNow(t('a'));
    s.playNow(t('a'));
    s.playNow(t('b'));
    expect(s.history.map((x) => x.videoId)).toEqual(['a']);
  });

  it('history is capped at 50, oldest dropped', async () => {
    const s = await freshStore();
    s.playNow(t('x0'));
    for (let i = 1; i <= 60; i++) s.playNow(t('x' + i));
    expect(s.history.length).toBe(50);
    expect(s.history[0].videoId).toBe('x10');
  });

  it('previous within threshold goes back and requeues current at front', async () => {
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    mod.playerControls.current = { getPosition: () => 1, seekTo: vi.fn() } as any;
    s.playNow(t('a'));
    s.enqueue(t('c'));
    s.playNow(t('b'));
    s.previous();
    expect(s.player.current?.videoId).toBe('a');
    expect(s.player.isPlaying).toBe(true);
    expect(s.queue.map((x) => x.videoId)).toEqual(['b', 'c']);
    expect(s.history).toEqual([]);
    mod.playerControls.current = null;
  });

  it('previous past threshold restarts via seekTo(0)', async () => {
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    const seekTo = vi.fn();
    mod.playerControls.current = { getPosition: () => 10, seekTo } as any;
    s.playNow(t('a'));
    s.playNow(t('b'));
    s.previous();
    expect(seekTo).toHaveBeenCalledWith(0);
    expect(s.player.current?.videoId).toBe('b');
    mod.playerControls.current = null;
  });

  it('previous with empty history restarts', async () => {
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    const seekTo = vi.fn();
    mod.playerControls.current = { getPosition: () => 0, seekTo } as any;
    s.playNow(t('a'));
    s.previous();
    expect(seekTo).toHaveBeenCalledWith(0);
    mod.playerControls.current = null;
  });

  it('previous on a live track with empty history does not seek', async () => {
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    const seekTo = vi.fn();
    mod.playerControls.current = { getPosition: () => 0, seekTo } as any;
    s.playNow({ ...t('L'), isLive: true });
    s.previous();
    expect(seekTo).not.toHaveBeenCalled();
    mod.playerControls.current = null;
  });
});

describe('persisted current + history', () => {
  it('stripSignedUrls removes every URL field and _formats', async () => {
    const { stripSignedUrls } = await import('../../src/lib/store.svelte');
    const out = stripSignedUrls({ ...t('a'), hlsUrl: '/h', liveStreamUrl: '/l', _formats: [] as any });
    expect(out.audioUrl).toBe('');
    expect(out.hlsUrl).toBeUndefined();
    expect(out.liveStreamUrl).toBeUndefined();
    expect('_formats' in out).toBe(false);
    expect(out.videoId).toBe('a');
  });

  it('flush writes current, position and history without URLs', async () => {
    const s = await freshStore();
    s.playNow(t('a'));
    s.playNow(t('b'));
    s.setPosition(42);
    await new Promise((r) => setTimeout(r, 250));
    const cur = JSON.parse(localStorage.getItem('hum.current')!);
    expect(cur.track.videoId).toBe('b');
    expect(cur.track.audioUrl).toBe('');
    expect(cur.pos).toBe(42);
    const hist = JSON.parse(localStorage.getItem('hum.history')!);
    expect(hist.map((x: any) => x.videoId)).toEqual(['a']);
    expect(hist[0].audioUrl).toBe('');
  });

  it('flush removes hum.current when nothing is playing', async () => {
    const s = await freshStore();
    s.playNow(t('a'));
    await new Promise((r) => setTimeout(r, 250));
    s.next();
    await new Promise((r) => setTimeout(r, 250));
    expect(localStorage.getItem('hum.current')).toBeNull();
  });

  it('rehydrates current paused at saved position; startPositionFor consumes it once', async () => {
    vi.resetModules();
    localStorage.setItem('hum.current', JSON.stringify({ track: { ...t('a'), audioUrl: '/stale', hlsUrl: '/h' }, pos: 77 }));
    localStorage.setItem('hum.history', JSON.stringify([{ ...t('z'), audioUrl: '/stale' }]));
    const { store: s } = await import('../../src/lib/store.svelte');
    expect(s.player.current?.videoId).toBe('a');
    expect(s.player.current?.audioUrl).toBe('');
    expect(s.player.current?.hlsUrl).toBeUndefined();
    expect(s.player.isPlaying).toBe(false);
    expect(s.player.positionSeconds).toBe(77);
    expect(s.history[0].audioUrl).toBe('');
    expect(s.startPositionFor(s.player.current!)).toBe(77);
    expect(s.startPositionFor(s.player.current!)).toBe(0);
  });

  it('rehydrate tolerates corrupt current', async () => {
    vi.resetModules();
    localStorage.setItem('hum.current', '{"track": null, "pos": "x"}');
    const { store: s } = await import('../../src/lib/store.svelte');
    expect(s.player.current).toBeNull();
    expect(s.player.positionSeconds).toBe(0);
  });

  it('startPositionFor uses a bookmark only for long vod', async () => {
    const s = await freshStore();
    localStorage.setItem('hum.bookmarks', JSON.stringify({ L: { pos: 300, at: 1 }, S: { pos: 50, at: 1 } }));
    expect(s.startPositionFor({ ...t('L'), durationSeconds: 1200 })).toBe(300);
    expect(s.startPositionFor({ ...t('S'), durationSeconds: 200 })).toBe(0);
    expect(s.startPositionFor({ ...t('L'), durationSeconds: 1200, isLive: true })).toBe(0);
  });
});

describe('review fixes — store', () => {
  it('previous under repeat all does not duplicate the track in the queue', async () => {
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    mod.playerControls.current = { getPosition: () => 0, seekTo: vi.fn() } as any;
    s.player.repeat = 'all';
    s.playNow(t('a'));
    s.enqueue(t('b'));
    s.enqueue(t('c'));
    s.next(); // a -> tail of queue and history
    s.previous();
    expect(s.player.current?.videoId).toBe('a');
    expect(s.queue.map((x) => x.videoId)).toEqual(['b', 'c']);
    mod.playerControls.current = null;
  });

  it('previous on a live track goes to history regardless of position', async () => {
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    mod.playerControls.current = { getPosition: () => 5000, seekTo: vi.fn() } as any;
    s.playNow(t('a'));
    s.playNow({ ...t('L'), isLive: true });
    s.previous();
    expect(s.player.current?.videoId).toBe('a');
    mod.playerControls.current = null;
  });
});

describe('pre-existing fixes — repeat replays', () => {
  it('repeat one: next() seeks to 0 and plays (same src never reloads)', async () => {
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    const seekTo = vi.fn();
    const play = vi.fn();
    mod.playerControls.current = { seekTo, play } as any;
    s.playNow(t('a'));
    s.player.repeat = 'one';
    s.player.isPlaying = false;
    s.next();
    expect(seekTo).toHaveBeenCalledWith(0);
    expect(play).toHaveBeenCalled();
    expect(s.player.isPlaying).toBe(true);
    expect(s.player.current?.videoId).toBe('a');
    mod.playerControls.current = null;
  });

  it('repeat all with a lone track: next() seeks to 0 and plays', async () => {
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    const seekTo = vi.fn();
    const play = vi.fn();
    mod.playerControls.current = { seekTo, play } as any;
    s.playNow(t('a'));
    s.player.repeat = 'all';
    s.next();
    expect(seekTo).toHaveBeenCalledWith(0);
    expect(play).toHaveBeenCalled();
    expect(s.player.current?.videoId).toBe('a');
    mod.playerControls.current = null;
  });
});

describe('code-review fixes — previous/replay', () => {
  it('history holds no signed URLs, so previous() hands back a track that refetches', async () => {
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    mod.playerControls.current = { getPosition: () => 0, seekTo: vi.fn() } as any;
    s.playNow({ ...t('a'), hlsUrl: '/hls/a', _formats: [] as any });
    s.playNow(t('b'));
    expect(s.history[0].audioUrl).toBe('');
    expect(s.history[0].hlsUrl).toBeUndefined();
    s.previous();
    expect(s.player.current?.videoId).toBe('a');
    expect(s.player.current?.audioUrl).toBe('');
    expect(s.player.current?.hlsUrl).toBeUndefined();
    mod.playerControls.current = null;
  });

  it('a live track in history comes back without its expired manifest URL', async () => {
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    mod.playerControls.current = { getPosition: () => 0, seekTo: vi.fn() } as any;
    s.playNow({ ...t('L'), isLive: true, audioUrl: '', liveStreamUrl: '/api/live/L/manifest.m3u8?exp=1&sig=x' });
    s.playNow(t('b'));
    s.previous();
    expect(s.player.current?.videoId).toBe('L');
    expect(s.player.current?.liveStreamUrl).toBeUndefined();
    mod.playerControls.current = null;
  });

  it('repeat on a live track does not seek (stays at the live edge)', async () => {
    const mod = await import('../../src/lib/store.svelte');
    const s = await freshStore();
    const seekTo = vi.fn();
    const play = vi.fn();
    mod.playerControls.current = { seekTo, play } as any;
    s.playNow({ ...t('L'), isLive: true });
    s.player.repeat = 'one';
    s.next();
    expect(seekTo).not.toHaveBeenCalled();
    expect(s.player.current?.videoId).toBe('L');
    s.player.repeat = 'all';
    s.next();
    expect(seekTo).not.toHaveBeenCalled();
    mod.playerControls.current = null;
  });
});

describe('copilot review — unreachable on initial fetch', () => {
  it('playNowById offers a sticky Retry that re-runs the fetch', async () => {
    const { ApiError, api } = await import('../../src/lib/api');
    const s = await freshStore();
    s.dismissToast();
    const video = vi.spyOn(api, 'video').mockRejectedValue(new ApiError(0, 'down'));
    await s.playNowById('abc');
    expect(s.toast?.message).toBe("Can't reach Hum server.");
    expect(s.toast?.action?.label).toBe('Retry');
    video.mockClear();
    s.toast!.action!.onclick();
    await new Promise((r) => setTimeout(r, 0));
    expect(video).toHaveBeenCalledWith('abc');
    video.mockRestore();
    s.dismissToast();
  });

  it('enqueueById retry re-runs enqueue, not play', async () => {
    const { ApiError, api } = await import('../../src/lib/api');
    const s = await freshStore();
    s.dismissToast();
    const video = vi.spyOn(api, 'video').mockRejectedValueOnce(new ApiError(0, 'down'));
    await s.enqueueById('q1');
    video.mockResolvedValueOnce({
      video_id: 'q1', title: 'T', author: 'A', channel_id: 'c', duration_seconds: 100, thumbnail_url: '',
      audio_formats: [{ itag: 140, mime_type: 'audio/mp4', bitrate: 128000, codec: 'mp4a.40.2', url: '/proxy/audio/q1?itag=140' }],
      video_formats: [],
    } as any);
    s.toast!.action!.onclick();
    await new Promise((r) => setTimeout(r, 0));
    expect(s.queue.map((x) => x.videoId)).toEqual(['q1']);
    expect(s.player.current).toBeNull();
    video.mockRestore();
    s.dismissToast();
  });
});
