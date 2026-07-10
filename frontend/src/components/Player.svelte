<script lang="ts">
  import { store, playerControls } from '../lib/store.svelte';
  import { formatDuration } from '../lib/format';
  import { api } from '../lib/api';
  import type { Track } from '../lib/types';
  import Icon from './Icon.svelte';
  import Marquee from './Marquee.svelte';
  import LivePill from './LivePill.svelte';

  // Safari plays the HLS-wrapped AAC stream for VOD; everyone else uses the
  // direct proxy URL. canPlayType for the HLS MIME is a Safari-only signal.
  // Live tracks are handled separately via hls.js (see live-mount effect).
  const hlsNative =
    typeof document !== 'undefined' &&
    document.createElement('audio').canPlayType('application/vnd.apple.mpegurl') !== '';

  function pickVodSrc(t: Track | null): string | undefined {
    if (!t || t.isLive) return undefined;
    if (hlsNative && t.hlsUrl) return t.hlsUrl;
    return t.audioUrl || undefined;
  }

  // play() rejects under autoplay policy or when a load interrupts it; an
  // uncaught rejection is console noise at best. Route every imperative play
  // through here.
  function safePlay(a: HTMLAudioElement | null) {
    void a?.play().catch(() => { /* requires user gesture / interrupted */ });
  }

  let el = $state<HTMLAudioElement | null>(null);
  let pos = $state(0);
  let dur = $state(0);
  let paused = $state(true);

  // Inspector logging for the <audio> element. Filter on `[hum:audio]` in
  // DevTools to see the full lifecycle of every load + seek. The snapshot
  // captures the bits that matter for diagnosing range-request behaviour:
  //   readyState   — 0..4 (HAVE_NOTHING..HAVE_ENOUGH_DATA)
  //   networkState — 0..3 (NETWORK_EMPTY..NETWORK_NO_SOURCE)
  //   buffered     — TimeRanges as [start, end] tuples; if Safari ever
  //                  shows a single 0..duration range it means the whole
  //                  file got downloaded instead of seek-by-range.
  function audioSnapshot(a: HTMLAudioElement) {
    const ranges: Array<[number, number]> = [];
    for (let i = 0; i < a.buffered.length; i++) {
      ranges.push([a.buffered.start(i), a.buffered.end(i)]);
    }
    return {
      ct: +a.currentTime.toFixed(2),
      dur: Number.isFinite(a.duration) ? +a.duration.toFixed(2) : a.duration,
      rs: a.readyState,
      ns: a.networkState,
      buffered: ranges,
      paused: a.paused,
      seeking: a.seeking,
    };
  }

  $effect(() => {
    // Dev-only: 20 listeners + a console line per media event is diagnostic
    // gold in DevTools and pure overhead in production.
    if (!el || !import.meta.env.DEV) return;
    const a = el;
    const log = (ev: Event) =>
      console.log('[hum:audio]', ev.type, audioSnapshot(a));
    const events = [
      'loadstart', 'loadedmetadata', 'loadeddata', 'canplay', 'canplaythrough',
      'play', 'playing', 'pause', 'seeking', 'seeked',
      'waiting', 'stalled', 'suspend', 'progress', 'error', 'ended',
      'durationchange', 'ratechange', 'emptied', 'abort',
    ];
    for (const e of events) a.addEventListener(e, log);
    console.log('[hum:audio] mounted', { src: a.currentSrc || a.src });
    return () => {
      for (const e of events) a.removeEventListener(e, log);
    };
  });
  // Track which videoIds we've already attempted to recover this session.
  // Using a videoId-keyed Set prevents the infinite retry loop that occurred when
  // the recovery path itself mutated store.player.current and reset a boolean flag.
  const recoveredVideoIds = new Set<string>();

  // `${videoId}:${codec}` keys; tracks which codec families we've already
  // attempted for a given video this session. Reset never; recover path
  // for a fresh restart of the app starts clean.
  const attemptedCodecs = new Set<string>();

  // Expose imperative controls on the shared playerControls ref so the global
  // keyboard handler in App.svelte can drive the <audio> element without
  // needing a reactive signal channel.
  $effect(() => {
    if (!el) {
      playerControls.current = null;
      return;
    }
    playerControls.current = {
      play:  () => safePlay(el),
      pause: () => el?.pause(),
      toggle: () => {
        if (!el) return;
        if (el.paused) safePlay(el); else el.pause();
      },
      seekBy: (delta) => {
        if (!el) return;
        const target = Math.max(0, Math.min((el.duration || dur || 0), el.currentTime + delta));
        el.currentTime = target;
      },
      setVolume: (v) => { if (el) el.volume = Math.max(0, Math.min(1, v)); },
      toggleMute: () => { if (el) el.muted = !el.muted; },
      getPosition: () => el?.currentTime ?? 0,
      restoreAt: (pos: number) => {
        const a = el;
        if (!a) return;
        if (a.readyState >= 1 /* HAVE_METADATA */) {
          a.currentTime = pos;
          return;
        }
        const onMeta = () => { a.currentTime = pos; };
        a.addEventListener('loadedmetadata', onMeta, { once: true });
      },
    };
    return () => { playerControls.current = null; };
  });

  // Reset Media Session metadata when the underlying videoId changes (not on
  // every recovery URL swap).
  let currentVideoId = $derived(store.player.current?.videoId ?? null);
  $effect(() => {
    const id = currentVideoId;
    if (!id) return;
    const t = store.player.current;
    if (t && 'mediaSession' in navigator) {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: t.title,
        artist: t.author,
        artwork: t.thumbnailUrl ? [{ src: t.thumbnailUrl }] : [],
      });
      try {
        navigator.mediaSession.setActionHandler('play',  () => safePlay(el));
        navigator.mediaSession.setActionHandler('pause', () => el?.pause());
        navigator.mediaSession.setActionHandler('nexttrack', () => store.next());
        navigator.mediaSession.setActionHandler('previoustrack', () => restart());
      } catch {
        // Some browsers don't support all actions.
      }
    }
  });

  // Live track mount: dynamically import hls.js and attach it to the audio
  // element. hls.js handles playlist refresh, segment scheduling, buffer
  // management, and discontinuity handling — all the things Safari's native
  // HLS engine doesn't do reliably for muxed-video live streams in <audio>.
  // On iOS Safari (no MSE) we fall back to native HLS via the src attribute.
  $effect(() => {
    const t = store.player.current;
    if (!el || !t?.isLive || !t.liveStreamUrl) return;

    let cancelled = false;
    let hls: import('hls.js').default | null = null;
    const audio = el;
    const src = t.liveStreamUrl;

    void (async () => {
      try {
        const { default: Hls } = await import('hls.js');
        if (cancelled) return;
        if (Hls.isSupported()) {
          hls = new Hls({
            // Start ~15s behind the live edge (was 5) so several fragments are
            // pre-buffered before playback reaches the buffer edge. Bridges the
            // cold-start fetch latency (master playlist + first segments) that
            // otherwise caused a rebuffer ~5s in. Live-latency is irrelevant for
            // a music radio stream, so trading it for runway is free.
            liveSyncDuration: 15,
            // Wider latency budget (was 15) — if the manifest poll is slow
            // (our /api/live takes ~500ms; YouTube's edge serves DVR with
            // sliding window), hls.js will tolerate falling further behind
            // live before declaring it broken.
            liveMaxLatencyDuration: 30,
            liveDurationInfinity: true,
            enableWorker: true,
            // Retry slack: each policy controls per-load timeout + retry
            // counts so a transient slow/failed manifest or segment fetch
            // doesn't go fatal and require user-visible recovery.
            manifestLoadPolicy: {
              default: {
                maxTimeToFirstByteMs: 8000,
                maxLoadTimeMs: 20000,
                timeoutRetry: { maxNumRetry: 4, retryDelayMs: 500, maxRetryDelayMs: 2000 },
                errorRetry: { maxNumRetry: 4, retryDelayMs: 1000, maxRetryDelayMs: 4000 },
              },
            },
            fragLoadPolicy: {
              default: {
                maxTimeToFirstByteMs: 8000,
                maxLoadTimeMs: 30000,
                timeoutRetry: { maxNumRetry: 4, retryDelayMs: 500, maxRetryDelayMs: 2000 },
                errorRetry: { maxNumRetry: 4, retryDelayMs: 1000, maxRetryDelayMs: 4000 },
              },
            },
          });
          // Defer play() until the first fragment is actually buffered.
          // Calling it on MEDIA_ATTACHED (which fires before any data exists)
          // forced a play -> waiting(stall) -> playing flicker on open. Waiting
          // for FRAG_BUFFERED means playback begins straight into buffered data.
          let playStarted = false;
          hls.on(Hls.Events.FRAG_BUFFERED, () => {
            if (playStarted) return;
            playStarted = true;
            void audio.play().catch(() => { /* user-gesture required */ });
          });
          hls.on(Hls.Events.ERROR, (_event, data) => {
            if (!data.fatal) return;
            console.warn('[hum:hls] fatal', data.type, data.details);
            if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
              hls?.startLoad();
            } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
              hls?.recoverMediaError();
            } else {
              hls?.destroy();
              hls = null;
              store.notify('Live stream failed. Try again.', 'error');
            }
          });
          hls.loadSource(src);
          hls.attachMedia(audio);
        } else if (audio.canPlayType('application/vnd.apple.mpegurl')) {
          audio.src = src;
          void audio.play().catch(() => { /* user-gesture required */ });
        } else {
          store.notify('Live playback is not supported in this browser.', 'error');
        }
      } catch (e) {
        console.warn('[hum:hls] failed to load', e);
        store.notify('Could not load live player.', 'error');
      }
    })();

    return () => {
      cancelled = true;
      if (hls) {
        try { hls.destroy(); } catch { /* ignore */ }
        hls = null;
      }
    };
  });

  // When a VOD track is rehydrated from localStorage its URLs are cleared.
  // Refetch on demand so playback can begin without a manual retry. Live
  // tracks handle their own refetch in the live-mount effect by re-running
  // when liveStreamUrl is missing.
  $effect(() => {
    const t = store.player.current;
    if (!t || t.isLive || pickVodSrc(t)) return;
    api.video(t.videoId).then((fresh) => {
      if (store.player.current?.videoId !== t.videoId) return;
      const same = fresh.audio_formats.find((f) => f.itag === t.itag) ?? fresh.audio_formats[0];
      if (same) {
        store.player.current = {
          ...t,
          audioUrl: same.url,
          hlsUrl: same.hls_url ?? undefined,
        };
      }
    }).catch(() => {
      store.notify('Could not load this track.', 'error');
    });
  });

  // Live track rehydrate: if a persisted live track has no liveStreamUrl
  // (stripped on flush), refetch via api.video for a fresh signed URL.
  $effect(() => {
    const t = store.player.current;
    if (!t?.isLive || t.liveStreamUrl) return;
    api.video(t.videoId).then((fresh) => {
      if (store.player.current?.videoId !== t.videoId) return;
      if (fresh.is_live && fresh.live_stream_url) {
        store.player.current = { ...t, liveStreamUrl: fresh.live_stream_url };
      }
    }).catch(() => {
      store.notify('Could not load this live stream.', 'error');
    });
  });

  // Progress percentage drives the gradient fill of the slider track.
  let progressPct = $derived.by(() => {
    const total = dur || store.player.current?.durationSeconds || 0;
    if (!total) return 0;
    return Math.min(100, Math.max(0, (pos / total) * 100));
  });

  function openExpanded() {
    if (typeof document !== 'undefined' && document.startViewTransition) {
      document.startViewTransition(() => store.expandPlayer());
    } else {
      store.expandPlayer();
    }
  }

  function advance() {
    store.next();
  }

  function restart() {
    if (el) el.currentTime = 0;
  }

  async function handleError() {
    const t = store.player.current;
    if (!t) return;
    // Live tracks: hls.js owns recovery (network restart, media recover,
    // fatal-error toast). Audio-element errors during hls.js playback are
    // already routed through hls.js's own error events.
    if (t.isLive) return;
    // If the playable URL is empty, the dedicated rehydrate $effect owns
    // refetching. Don't double-fetch and don't consume the retry slot.
    if (!pickVodSrc(t)) return;

    // Codec fallback path: if the track carries _formats and an untried
    // alternate-codec format exists, swap codec ONCE silently before
    // falling through to the refetch retry. This is the Brave fix —
    // opus may fail on certain Chromium builds, AAC may succeed.
    if (t._formats && t._formats.length > 0) {
      const currentCodec = t._formats.find((f) => f.itag === t.itag)?.codec;
      const attemptKey = `${t.videoId}:${currentCodec ?? ''}`;
      if (currentCodec && !attemptedCodecs.has(attemptKey)) {
        const alt = t._formats.find(
          (f) =>
            f.codec !== currentCodec &&
            !attemptedCodecs.has(`${t.videoId}:${f.codec}`)
        );
        if (alt) {
          attemptedCodecs.add(attemptKey);
          const lastPos = pos;
          const next: Track = {
            ...t,
            audioUrl: alt.url,
            hlsUrl: alt.hls_url ?? undefined,
            itag: alt.itag,
            bitrate: alt.bitrate,
            // qualityTier is preserved — fallback doesn't change user intent
          };
          store.player.current = next;
          if (el) {
            el.addEventListener(
              'loadedmetadata',
              () => { if (el) el.currentTime = lastPos; },
              { once: true },
            );
          }
          return;
        }
      }
    }

    if (recoveredVideoIds.has(t.videoId)) {
      // Already tried recovery once for this track — surface to user.
      store.notify(
        'Stream failed. Try again?',
        'error',
        {
          label: 'Retry',
          onclick: () => {
            // Allow another recovery attempt and reload.
            recoveredVideoIds.delete(t.videoId);
            if (el) { el.load(); safePlay(el); }
          },
        },
        0, // sticky — don't auto-dismiss the retry CTA
      );
      return;
    }
    recoveredVideoIds.add(t.videoId);
    try {
      const fresh = await api.video(t.videoId);
      const same = fresh.audio_formats.find((f) => f.itag === t.itag);
      if (same) {
        const lastPos = pos;
        const next: Track = {
          ...t,
          audioUrl: same.url,
          hlsUrl: same.hls_url ?? undefined,
        };
        store.player.current = next;
        if (el) {
          el.addEventListener('loadedmetadata', () => { if (el) el.currentTime = lastPos; }, { once: true });
        }
      }
    } catch {
      // Give up silently; user can hit Play again.
    }
  }
</script>

<div class="player" class:empty={!store.player.current} style="--progress: {progressPct}%">
  {#if store.player.current}
    <!-- Single <audio> for VOD + live. For live, src stays unset so hls.js
         can attach via MSE (sets a blob URL itself). For VOD the src binding
         drives playback as usual. -->
    <audio
      bind:this={el}
      bind:currentTime={pos}
      bind:duration={dur}
      bind:paused
      src={pickVodSrc(store.player.current)}
      preload="metadata"
      onended={advance}
      onerror={handleError}
      autoplay
    ></audio>

    <div class="info">
      <button class="art-button" onclick={openExpanded} aria-label="Open now playing">
        <div
          class="art"
          style:view-transition-name={store.player.isExpanded ? 'none' : 'now-playing-art'}
        >
          {#if store.player.current.thumbnailUrl}
            <img src={store.player.current.thumbnailUrl} alt="" />
          {:else}
            <div class="art-placeholder"></div>
          {/if}
        </div>
      </button>
      <div class="meta">
        {#key store.player.current.videoId}
          <div class="title"><Marquee text={store.player.current.title} /></div>
          <div class="author">{store.player.current.author}</div>
        {/key}
      </div>
    </div>

    <div class="transport">
      <div class="controls">
        <button
          class="mode"
          class:active={store.player.shuffle}
          onclick={() => store.toggleShuffle()}
          aria-label={store.player.shuffle ? 'Shuffle on' : 'Shuffle off'}
          aria-pressed={store.player.shuffle}
        >
          <Icon name="shuffle" size={18} />
        </button>
        {#if !store.player.current.isLive}
          <button class="ctrl" onclick={restart} aria-label="Restart track">
            <Icon name="skip-back" size={20} />
          </button>
        {/if}
        <button
          class="ctrl ctrl-play"
          onclick={() => paused ? safePlay(el) : el?.pause()}
          aria-label={paused ? 'Play' : 'Pause'}
        >
          {#if paused}
            <Icon name="play" size={22} />
          {:else}
            <Icon name="pause" size={22} />
          {/if}
        </button>
        <button class="ctrl" onclick={advance} aria-label="Next track">
          <Icon name="skip-forward" size={20} />
        </button>
        <button
          class="mode"
          class:active={store.player.repeat !== 'off'}
          onclick={() => store.cycleRepeat()}
          aria-label={'Repeat ' + store.player.repeat}
        >
          {#if store.player.repeat === 'one'}
            <Icon name="repeat-1" size={18} />
          {:else}
            <Icon name="repeat" size={18} />
          {/if}
        </button>
      </div>

      {#if store.player.current.isLive}
        <div class="live-row">
          <LivePill />
        </div>
      {:else}
        <div class="scrubber">
          <span class="time">{formatDuration(pos)}</span>
          <input
            type="range"
            min="0"
            max={dur || store.player.current.durationSeconds}
            step="1"
            bind:value={pos}
            aria-label="Seek"
            aria-valuetext={formatDuration(pos) + ' of ' + formatDuration(dur || store.player.current.durationSeconds)}
          />
          <span class="time">{formatDuration(dur || store.player.current.durationSeconds)}</span>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  /* The player is the visual hero. It floats above all page
     content, frosted glass over the artwork-tinted background. */
  .player {
    position: fixed;
    left: var(--s-4);
    right: var(--s-4);
    bottom: var(--s-4);
    z-index: 20;
    display: grid;
    grid-template-columns: minmax(220px, 1fr) minmax(340px, 2fr);
    gap: var(--s-5);
    align-items: center;
    padding: var(--s-3) var(--s-5);
    min-height: var(--player-h);
    background: rgba(14, 16, 22, 0.55);
    border: 1px solid var(--hairline);
    border-radius: var(--r-xl);
    box-shadow:
      var(--inner-top-highlight),
      var(--shadow-3);
    backdrop-filter: blur(60px) saturate(200%);
    -webkit-backdrop-filter: blur(60px) saturate(200%);
    animation: fade-in var(--dur-base) var(--ease);
  }
  .player.empty { display: none; }

  /* ---- Track info (left) ------------------------------------ */
  .info {
    display: flex;
    align-items: center;
    gap: var(--s-4);
    min-width: 0;
  }
  /* Reset button appearance so the art button is a pure click target. */
  .art-button {
    flex-shrink: 0;
    padding: 0;
    border: none;
    border-radius: var(--r-md);
    background: transparent;
    box-shadow: none;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    cursor: pointer;
    display: block;
  }
  .art-button:hover:not(:disabled) {
    background: transparent;
    transform: scale(1.04);
  }
  .art {
    flex-shrink: 0;
    width: 64px;
    height: 64px;
    border-radius: var(--r-md);
    overflow: hidden;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.5);
    border: 1px solid var(--hairline-soft);
  }
  .art img,
  .art-placeholder {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .art-placeholder {
    background: linear-gradient(135deg, var(--glass-3), var(--glass-1));
  }
  .meta {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  /* Editorial display type for the now-playing title — this is
     the touch that makes the bar feel like Apple Music's
     "Now Playing" card rather than a plain audio HUD. */
  .title {
    font-family: var(--font-sans);
    font-size: var(--t-xl);
    line-height: var(--lh-tight);
    letter-spacing: -0.01em;
    color: var(--ink);
    overflow: hidden;
    min-width: 0;
    animation: crossfade var(--dur-base) var(--ease);
    /* The mini-player capsule sits over the chromatic wash too. */
    text-shadow: var(--text-shadow-chromatic);
  }
  .author {
    font-size: var(--t-sm);
    color: var(--ink-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    animation: crossfade var(--dur-slow) var(--ease);
  }

  /* ---- Transport (right) ------------------------------------ */
  .transport {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }
  .controls {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: var(--s-2);
  }
  .ctrl {
    display: inline-grid;
    place-items: center;
    width: 36px;
    height: 36px;
    padding: 0;
    background: transparent;
    border: none;
    border-radius: 50%;
    color: var(--ink);
    box-shadow: none;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    transition:
      transform var(--dur-fast) var(--ease),
      background var(--dur-fast) var(--ease),
      color var(--dur-fast) var(--ease);
  }
  .ctrl:hover:not(:disabled) {
    background: var(--glass-2);
    transform: scale(1.05);
  }
  .ctrl-play {
    width: 44px;
    height: 44px;
    background: var(--ink);
    color: #0b0d11;
    box-shadow: 0 6px 18px rgba(255, 255, 255, 0.15);
  }
  .ctrl-play:hover:not(:disabled) {
    background: white;
    transform: scale(1.06);
  }

  .live-row {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 32px;
  }

  .scrubber {
    display: grid;
    grid-template-columns: 44px 1fr 44px;
    align-items: center;
    gap: var(--s-3);
  }
  .scrubber input[type="range"] {
    width: 100%;
  }
  .time {
    color: var(--ink-muted);
    font-size: var(--t-sm);
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.02em;
  }
  .time:last-of-type { text-align: right; }

  button.mode {
    width: 36px;
    height: 36px;
    padding: 0;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: transparent;
    border: 1px solid transparent;
    color: var(--ink-muted);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
  button.mode:hover { color: var(--ink); background: var(--glass-2); }
  button.mode.active {
    color: var(--accent);
    background: var(--glass-2);
    border-color: var(--hairline);
  }

  @media (max-width: 720px) {
    .player {
      display: flex;
      flex-direction: column;
      align-items: stretch;
      gap: var(--s-2);
      padding: var(--s-3) var(--s-4);
      /* Sit above tab bar (--tab-h) + small gap */
      bottom: calc(var(--tab-h) + var(--s-2));
      left: var(--s-2);
      right: var(--s-2);
      border-radius: var(--r-lg);
    }
    .info { flex: 0 0 auto; }
    .controls { flex: 0 0 auto; }
    .time { display: none; }
  }
</style>
