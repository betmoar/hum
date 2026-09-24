import type { Track, Quality, AudioFormat, VideoDetails } from './types';
import { migrateLegacyKeys } from './migrateLegacy';
import { api, isUnreachable } from './api';
import { detectAudioEnv } from './browserEnv';
import { pickForTier } from './pickAudio';
import { getBookmark, BOOKMARK_MIN_DURATION_S } from './bookmarks';
import { isBookmarkable, isSeekable } from './contentKind';

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
  seekTo?: (seconds: number) => void;
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
  // Last known playback position of `current`, written by Player every few
  // seconds and on pause. Persisted with current so a reload resumes there.
  positionSeconds: number;
  shuffle: boolean;
  repeat: 'off' | 'one' | 'all';
  isExpanded: boolean;
  // True iff AirPlay is supported, a target is available, and the current
  // track is routable (not live). Reactive so both Player and NowPlaying gate
  // their buttons on the same source. Player owns the writes (derived from its
  // airplay-control instance); NowPlaying only reads.
  airplayCapable: boolean;
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
const KEY_CURRENT = 'hum.current';
const KEY_HISTORY = 'hum.history';
export const HISTORY_MAX = 50;
export const UNREACHABLE_MESSAGE = "Can't reach Hum server.";
// "Previous" restarts the current track once it has played this long;
// before that it goes back to the prior track (common player convention).
export const PREVIOUS_RESTART_THRESHOLD_S = 3;
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

// The ONE place signed URLs are stripped before persistence and after
// rehydrate. audioUrl/hlsUrl/liveStreamUrl all expire; _formats carries more
// of them. A new signed-URL field on Track is stripped here and nowhere else.
export function stripSignedUrls(t: Track): Track {
  const { _formats, ...rest } = t;
  void _formats;
  return { ...rest, audioUrl: '', hlsUrl: undefined, liveStreamUrl: undefined };
}

type PersistedCurrent = { track: Track; pos: number };

function loadCurrent(): PersistedCurrent | null {
  const v = loadJson<Partial<PersistedCurrent> | null>(KEY_CURRENT, null);
  if (!v || !v.track || typeof v.track !== 'object' || typeof v.track.videoId !== 'string') return null;
  const pos = typeof v.pos === 'number' && Number.isFinite(v.pos) && v.pos > 0 ? v.pos : 0;
  return { track: stripSignedUrls(v.track), pos };
}

function loadTrackList(key: string): Track[] {
  const v = loadJson<unknown>(key, []);
  if (!Array.isArray(v)) return [];
  return (v as Track[]).filter((t) => t && typeof t.videoId === 'string').map(stripSignedUrls);
}

const restored = loadCurrent();

class AppStore {
  settings = $state<Settings>({
    bearerToken: loadString(KEY_BEARER),
    defaultQuality: (loadString(KEY_DEFAULT_QUALITY) as Quality | null) === 'low' ? 'low' : 'hi',
    musicOnly: loadString(KEY_MUSIC_ONLY) === 'false' ? false : true,
  });
  // Stored audioUrl/hlsUrl are signed with a TTL; on rehydrate they're almost
  // certainly stale. stripSignedUrls clears them so the Player refetches via
  // api.video on next play — a surviving hlsUrl makes pickVodSrc() return a
  // dead URL on Safari and skips the rehydrate refetch entirely.
  queue = $state<Track[]>(loadTrackList(KEY_QUEUE));
  // Played tracks, most recent last. Backs previous(); capped at HISTORY_MAX.
  history = $state<Track[]>(loadTrackList(KEY_HISTORY));
  // A restored track comes back PAUSED (isPlaying false) at its saved
  // position — a page reload must never start audio on its own.
  player = $state<PlayerState>({
    current: restored?.track ?? null,
    isPlaying: false,
    positionSeconds: restored?.pos ?? 0,
    shuffle: false,
    repeat: 'off',
    isExpanded: false,
    airplayCapable: false,
  });
  toast = $state<Toast | null>(null);

  #saveTimer: ReturnType<typeof setTimeout> | null = null;
  // videoId of the track restored from storage; startPositionFor() hands out
  // its saved position exactly once.
  #restoredId: string | null = restored?.track.videoId ?? null;
  #toastTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    // Persist queue + bearer + settings on change, debounced.
    $effect.root(() => {
      $effect(() => {
        // Touch the reactive deps so this effect re-runs on change.
        void this.queue.length;
        void this.history.length;
        void this.player.current;
        void this.player.positionSeconds;
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
      // Signed URLs must never be persisted — every Track goes through
      // stripSignedUrls (the single strip point).
      localStorage.setItem(KEY_QUEUE, JSON.stringify(this.queue.map(stripSignedUrls)));
      localStorage.setItem(KEY_HISTORY, JSON.stringify(this.history.map(stripSignedUrls)));
      const cur = this.player.current;
      if (cur) {
        const persisted: PersistedCurrent = { track: stripSignedUrls(cur), pos: this.player.positionSeconds };
        localStorage.setItem(KEY_CURRENT, JSON.stringify(persisted));
      } else {
        localStorage.removeItem(KEY_CURRENT);
      }
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

  // History entries are stored stripped: by the time previous() brings one
  // back its signed URLs may have expired, and an empty URL is what makes
  // the Player's rehydrate effects refetch fresh ones (VOD and live).
  #pushHistory(t: Track): void {
    const next = [...this.history, stripSignedUrls(t)];
    this.history = next.length > HISTORY_MAX ? next.slice(next.length - HISTORY_MAX) : next;
  }

  playNow(t: Track): void {
    const prev = this.player.current;
    if (prev && prev.videoId !== t.videoId) this.#pushHistory(prev);
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
      this.#replayCurrent();
      return;
    }

    // No queue: 'all' wraps current if present; otherwise stop.
    if (this.queue.length === 0) {
      if (this.player.repeat === 'all' && this.player.current) {
        this.#replayCurrent();
        return;
      }
      if (this.player.current) this.#pushHistory(this.player.current);
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

    if (this.player.current) this.#pushHistory(this.player.current);
    this.queue = rest;
    this.player.current = next;
    this.player.isPlaying = true;
    this.player.positionSeconds = 0;
  }

  /**
   * Go to the previous track, or restart the current one once it has played
   * past PREVIOUS_RESTART_THRESHOLD_S (or when there is no history). The
   * track being left goes back to the FRONT of the queue so "next" returns
   * to it.
   */
  previous(): void {
    const cur = this.player.current;
    if (!cur) return;
    // Restart only applies to seekable content; on live, previous always
    // means "go back" (its playhead position is meaningless here).
    const seekable = isSeekable(cur);
    const pos = playerControls.current?.getPosition?.() ?? 0;
    if (this.history.length === 0 || (seekable && pos > PREVIOUS_RESTART_THRESHOLD_S)) {
      if (seekable) playerControls.current?.seekTo?.(0);
      return;
    }
    const prior = this.history[this.history.length - 1];
    this.history = this.history.slice(0, -1);
    // Under repeat 'all', next() also parked `prior` at the queue tail;
    // taking it back must remove that copy or each round trip duplicates it.
    let rest = this.queue;
    const tail = rest[rest.length - 1];
    if (this.player.repeat === 'all' && tail && tail.videoId === prior.videoId && tail.queueId === prior.queueId) {
      rest = rest.slice(0, -1);
    }
    this.queue = [cur, ...rest];
    this.player.current = prior;
    this.player.isPlaying = true;
    this.player.positionSeconds = 0;
  }

  /** Record the last known playback position (persisted with current). */
  setPosition(seconds: number): void {
    if (Number.isFinite(seconds) && seconds >= 0) this.player.positionSeconds = seconds;
  }

  /**
   * Where playback of `t` should start: the saved position for the track
   * restored on load (once), else a resume bookmark for long VOD, else 0.
   */
  startPositionFor(t: Track): number {
    // One-shot either way: whichever track the player asks about first
    // settles the restore, so a later replay of that video doesn't jump.
    const restoredId = this.#restoredId;
    this.#restoredId = null;
    if (restoredId !== null && t.videoId === restoredId) {
      return isSeekable(t) ? this.player.positionSeconds : 0;
    }
    if (!isBookmarkable(t) || t.durationSeconds < BOOKMARK_MIN_DURATION_S) return 0;
    return getBookmark(t.videoId) ?? 0;
  }

  // Replaying the same track can't go through `current`: the src string is
  // unchanged, so the element never reloads and stays parked at the end.
  // Drive the element directly instead.
  // Live has no start to go back to — rewinding would land at the start of
  // the DVR buffer or stall, so it just keeps playing at the live edge.
  #replayCurrent(): void {
    const cur = this.player.current;
    this.player.isPlaying = true;
    if (cur && isSeekable(cur)) {
      this.player.positionSeconds = 0;
      playerControls.current?.seekTo?.(0);
    }
    playerControls.current?.play();
  }

  notify(message: string, kind: Toast['kind'] = 'info', action?: Toast['action'], durationMs = 5000): void {
    this.toast = { message, kind, action };
    if (this.#toastTimer) clearTimeout(this.#toastTimer);
    if (durationMs > 0) {
      this.#toastTimer = setTimeout(() => this.dismissToast(), durationMs);
    }
  }

  /**
   * The request never reached Hum (see api.isUnreachable). Distinct copy from
   * the YouTube-side "Stream failed" so the user knows which box to check.
   * Sticky when a retry is offered.
   */
  notifyUnreachable(retry?: () => void): void {
    if (retry) {
      this.notify(UNREACHABLE_MESSAGE, 'error', { label: 'Retry', onclick: () => { this.dismissToast(); retry(); } }, 0);
    } else {
      this.notify(UNREACHABLE_MESSAGE, 'error');
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
    } catch (e) {
      if (isUnreachable(e)) this.notifyUnreachable();
      else this.notify('Could not load this track.', 'error');
      return null;
    }
  }

  async playNowById(videoId: string): Promise<void> {
    const t = await this.#fetchTrack(videoId, this.settings.defaultQuality);
    if (t) this.playNow(t);
  }

  /** Enqueue tracks from listing metadata alone (playlist browse) — no
   * per-track /api/video call. URLs stay empty; Player.svelte's rehydrate
   * effect fetches a fresh signed URL when the track starts, exactly as for
   * a queue restored from localStorage. */
  enqueueStubs(
    items: { videoId: string; title: string; author: string; durationSeconds: number; thumbnailUrl: string }[],
    opts?: { next?: boolean },
  ): void {
    const stubs = items.map((it) => ({ ...it, audioUrl: '', itag: 0, queueId: crypto.randomUUID() }));
    this.queue = opts?.next ? [...stubs, ...this.queue] : [...this.queue, ...stubs];
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
