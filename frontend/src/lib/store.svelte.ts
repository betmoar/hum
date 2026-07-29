import type { Track, Quality, AudioFormat, VideoDetails } from './types';
import { migrateLegacyKeys } from './migrateLegacy';
import { api } from './api';
import { detectAudioEnv } from './browserEnv';
import { pickForTier } from './pickAudio';

// Rename legacy `streamtube.*` keys to `hum.*` before any reads. Idempotent.
migrateLegacyKeys();

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

// Module-level non-reactive ref — NOT $state. Components write .current on
// mount; event handlers read .current at dispatch time. Plain mutable object
// avoids reactivity churn for what's effectively an imperative method handle.
export const playerControls: { current: PlayerControls | null } = { current: null };

type Settings = {
  bearerToken: string | null;
  defaultQuality: Quality;
  musicOnly: boolean;
};

type PlayerState = {
  current: Track | null;
  isPlaying: boolean;
  positionSeconds: number;
  shuffle: boolean;
  repeat: 'off' | 'one' | 'all';
  isExpanded: boolean;
};

type Toast = {
  message: string;
  kind: 'info' | 'error';
  action?: { label: string; onclick: () => void };
};

const KEY_BEARER = 'hum.bearer';
const KEY_QUEUE = 'hum.queue';
const KEY_DEFAULT_QUALITY = 'hum.defaultQuality';
const KEY_MUSIC_ONLY = 'hum.musicOnly';
const PERSIST_DEBOUNCE_MS = 200;

function loadString(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

class AppStore {
  settings = $state<Settings>({
    bearerToken: loadString(KEY_BEARER),
    defaultQuality: (loadString(KEY_DEFAULT_QUALITY) as Quality | null) === 'low' ? 'low' : 'hi',
    musicOnly: loadString(KEY_MUSIC_ONLY) === 'false' ? false : true,
  });
  queue = $state<Track[]>(
    // Stored audioUrl/hlsUrl are signed with a TTL; on rehydrate they're almost
    // certainly stale. Clear BOTH so the Player refetches via api.video on next
    // play — a surviving hlsUrl makes pickVodSrc() return a dead URL on Safari
    // and skips the rehydrate refetch entirely.
    loadJson<Track[]>(KEY_QUEUE, []).map((t) => ({ ...t, audioUrl: '', hlsUrl: undefined }))
  );
  player = $state<PlayerState>({ current: null, isPlaying: false, positionSeconds: 0, shuffle: false, repeat: 'off', isExpanded: false });
  toast = $state<Toast | null>(null);

  #saveTimer: ReturnType<typeof setTimeout> | null = null;
  #toastTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    // Persist queue + bearer + settings on change, debounced.
    $effect.root(() => {
      $effect(() => {
        // Touch the reactive deps so this effect re-runs on change.
        void this.queue.length;
        void this.settings.bearerToken;
        void this.settings.defaultQuality;
        void this.settings.musicOnly;
        if (this.#saveTimer) clearTimeout(this.#saveTimer);
        this.#saveTimer = setTimeout(() => this.#flush(), PERSIST_DEBOUNCE_MS);
      });
    });
  }

  #flush(): void {
    try {
      if (this.settings.bearerToken) {
        localStorage.setItem(KEY_BEARER, this.settings.bearerToken);
      } else {
        localStorage.removeItem(KEY_BEARER);
      }
      localStorage.setItem(KEY_DEFAULT_QUALITY, this.settings.defaultQuality);
      localStorage.setItem(KEY_MUSIC_ONLY, String(this.settings.musicOnly));
      const queueToPersist = this.queue.map((t) => {
        const { _formats, ...rest } = t;
        // Signed URLs must not be persisted: audioUrl, hlsUrl, liveStreamUrl
        // all expire. If you add a new signed-URL field to Track, strip it
        // here AND in the queue rehydrate map above.
        return { ...rest, audioUrl: '', hlsUrl: undefined, liveStreamUrl: undefined };
      });
      localStorage.setItem(KEY_QUEUE, JSON.stringify(queueToPersist));
    } catch {
      // Storage may be unavailable (private browsing). Best-effort.
    }
  }

  setToken(t: string): void {
    this.settings.bearerToken = t;
  }

  invalidateToken(): void {
    this.settings.bearerToken = null;
  }

  setDefaultQuality(q: Quality): void {
    this.settings.defaultQuality = q;
  }

  setMusicOnly(v: boolean): void {
    this.settings.musicOnly = v;
  }

  enqueue(t: Track): void {
    this.queue = [...this.queue, { ...t, queueId: t.queueId ?? crypto.randomUUID() }];
  }

  playNext(t: Track): void {
    this.queue = [{ ...t, queueId: t.queueId ?? crypto.randomUUID() }, ...this.queue];
  }

  playNow(t: Track): void {
    this.player.current = t;
    this.player.isPlaying = true;
    this.player.positionSeconds = 0;
  }

  expandPlayer(): void {
    if (!this.player.current) return;
    this.player.isExpanded = true;
  }

  collapsePlayer(): void {
    this.player.isExpanded = false;
  }

  togglePlayerExpanded(): void {
    this.player.isExpanded = !this.player.isExpanded;
  }

  toggleShuffle(): void {
    this.player.shuffle = !this.player.shuffle;
  }

  cycleRepeat(): void {
    const order: PlayerState['repeat'][] = ['off', 'all', 'one'];
    const i = order.indexOf(this.player.repeat);
    this.player.repeat = order[(i + 1) % order.length];
  }

  next(): void {
    // 'one' replays current if there is one.
    if (this.player.repeat === 'one' && this.player.current) {
      this.player.positionSeconds = 0;
      this.player.current = { ...this.player.current };
      this.player.isPlaying = true;
      return;
    }

    // No queue: 'all' wraps current if present; otherwise stop.
    if (this.queue.length === 0) {
      if (this.player.repeat === 'all' && this.player.current) {
        this.player.positionSeconds = 0;
        this.player.current = { ...this.player.current };
        return;
      }
      this.player.current = null;
      this.player.isPlaying = false;
      this.player.positionSeconds = 0;
      return;
    }

    // Pick the next track.
    let idx = 0;
    if (this.player.shuffle && this.queue.length > 1) {
      idx = Math.floor(Math.random() * this.queue.length);
    }
    const next = this.queue[idx];
    const rest = this.queue.filter((_, i) => i !== idx);

    // 'all' pushes the just-played current to the end of the rest.
    if (this.player.repeat === 'all' && this.player.current) {
      rest.push(this.player.current);
    }

    this.queue = rest;
    this.player.current = next;
    this.player.isPlaying = true;
    this.player.positionSeconds = 0;
  }

  /** Restart the current track from the beginning. */
  restart(): void {
    if (!this.player.current) return;
    this.player.positionSeconds = 0;
    // Force a reactive update so the Player picks up the position reset.
    this.player.current = { ...this.player.current };
  }

  notify(message: string, kind: Toast['kind'] = 'info', action?: Toast['action'], durationMs = 5000): void {
    this.toast = { message, kind, action };
    if (this.#toastTimer) clearTimeout(this.#toastTimer);
    if (durationMs > 0) {
      this.#toastTimer = setTimeout(() => this.dismissToast(), durationMs);
    }
  }

  dismissToast(): void {
    this.toast = null;
    if (this.#toastTimer) clearTimeout(this.#toastTimer);
    this.#toastTimer = null;
  }

  remove(idx: number): void {
    if (idx < 0 || idx >= this.queue.length) return;
    this.queue = this.queue.filter((_, i) => i !== idx);
  }

  reorder(from: number, to: number): void {
    if (from === to) return;
    if (from < 0 || from >= this.queue.length) return;
    if (to < 0 || to >= this.queue.length) return;
    const next = [...this.queue];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    this.queue = next;
  }

  clear(): void {
    this.queue = [];
  }

  #buildTrack(d: VideoDetails, fmt: AudioFormat | null, tier: Quality | undefined): Track {
    if (d.is_live) {
      return {
        videoId: d.video_id,
        title: d.title,
        author: d.author,
        durationSeconds: 0,
        thumbnailUrl: d.thumbnail_url,
        audioUrl: '',
        itag: 0,
        bitrate: 0,
        qualityTier: undefined,
        isLive: true,
        liveStreamUrl: d.live_stream_url ?? undefined,
        _formats: [],
      };
    }
    return {
      videoId: d.video_id,
      title: d.title,
      author: d.author,
      durationSeconds: d.duration_seconds,
      thumbnailUrl: d.thumbnail_url,
      audioUrl: fmt!.url,
      hlsUrl: fmt!.hls_url ?? undefined,
      itag: fmt!.itag,
      viewCount: d.view_count ?? undefined,
      bitrate: fmt!.bitrate,
      qualityTier: tier,
      isLive: false,
      _formats: d.audio_formats,
    };
  }

  async #fetchTrack(videoId: string, tier: Quality): Promise<Track | null> {
    try {
      const d = await api.video(videoId);
      // Live tracks have no audio_formats — build directly from the live
      // manifest URL. Returned (not played) so the caller decides play/enqueue.
      if (d.is_live) return this.#buildTrack(d, null, undefined);
      const fmt = pickForTier(d.audio_formats, tier, detectAudioEnv());
      if (!fmt) { this.notify('No playable format found.', 'error'); return null; }
      return this.#buildTrack(d, fmt, tier);
    } catch {
      this.notify('Could not load this track.', 'error');
      return null;
    }
  }

  async playNowById(videoId: string): Promise<void> {
    const t = await this.#fetchTrack(videoId, this.settings.defaultQuality);
    if (t) this.playNow(t);
  }

  async enqueueById(videoId: string): Promise<void> {
    const t = await this.#fetchTrack(videoId, this.settings.defaultQuality);
    if (t) this.enqueue(t);
  }

  async playNextById(videoId: string): Promise<void> {
    const t = await this.#fetchTrack(videoId, this.settings.defaultQuality);
    if (t) this.playNext(t);
  }

  playNowAtTier(d: VideoDetails, tier: Quality): void {
    if (d.is_live) {
      this.playNow(this.#buildTrack(d, null, undefined));
      return;
    }
    const fmt = pickForTier(d.audio_formats, tier, detectAudioEnv());
    if (!fmt) {
      this.notify('No playable format found.', 'error');
      return;
    }
    this.playNow(this.#buildTrack(d, fmt, tier));
  }

  #qualitySwitchToken = 0;

  async switchQuality(tier: Quality): Promise<void> {
    const cur = this.player.current;
    if (!cur) return;
    if (cur.qualityTier === tier) return;

    // Capture position BEFORE the network round-trip so we restore where
    // the user actually was, not "wherever the track had drifted to."
    const lastPos = playerControls.current?.getPosition?.() ?? 0;

    const token = ++this.#qualitySwitchToken;
    try {
      const fresh = await api.video(cur.videoId);
      if (token !== this.#qualitySwitchToken) return;

      const fmt = pickForTier(fresh.audio_formats, tier, detectAudioEnv());
      if (!fmt) {
        this.notify('Could not switch quality.', 'error');
        return;
      }
      this.player.current = {
        ...cur,
        audioUrl: fmt.url,
        hlsUrl: fmt.hls_url ?? undefined,
        itag: fmt.itag,
        bitrate: fmt.bitrate,
        qualityTier: tier,
        _formats: fresh.audio_formats,
      };
      playerControls.current?.restoreAt?.(lastPos);
    } catch {
      if (token === this.#qualitySwitchToken) {
        this.notify('Could not switch quality.', 'error');
      }
    }
  }
}

export const store = new AppStore();
