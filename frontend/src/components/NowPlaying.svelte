<script lang="ts">
  import { store, playerControls } from '../lib/store.svelte';
  import { formatDuration, formatViewCount, formatBitrate } from '../lib/format';
  import { router } from '../routes.svelte';
  import Icon from './Icon.svelte';
  import LivePill from './LivePill.svelte';

  let livePos = $state(0);
  let liveDur = $state(0);
  let livePaused = $state(true);

  // Poll the audio element every 250ms while the overlay is open.
  // Pragmatic approach: avoids wiring another reactive channel for a hobby app.
  $effect(() => {
    if (!store.player.isExpanded) return;
    const tick = () => {
      const audio = document.querySelector('audio') as HTMLAudioElement | null;
      if (audio) {
        livePos = audio.currentTime;
        liveDur = audio.duration || (store.player.current?.durationSeconds ?? 0);
        livePaused = audio.paused;
      }
    };
    tick();
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
  });

  function close() {
    if (typeof document !== 'undefined' && document.startViewTransition) {
      document.startViewTransition(() => store.collapsePlayer());
    } else {
      store.collapsePlayer();
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && store.player.isExpanded) {
      e.preventDefault();
      e.stopPropagation();
      close();
    }
  }

  function onScrub(e: Event) {
    // Scrubber is gated by !t.isLive in the template, so only audio.
    const audio = document.querySelector('audio') as HTMLAudioElement | null;
    if (audio) {
      audio.currentTime = Number((e.target as HTMLInputElement).value);
    }
  }

  function togglePlayPause() {
    playerControls.current?.toggle();
  }

  function restartTrack() {
    // Restart button is gated by !t.isLive in the template, so only audio.
    const audio = document.querySelector('audio') as HTMLAudioElement | null;
    if (audio) audio.currentTime = 0;
  }

  function openQueue() {
    // Collapse the expanded view, then route to /queue. Two steps so the
    // view-transition on collapse plays cleanly before the route change.
    const navigate = () => {
      store.collapsePlayer();
      router.navigate('/queue');
    };
    if (typeof document !== 'undefined' && document.startViewTransition) {
      document.startViewTransition(navigate);
    } else {
      navigate();
    }
  }

  /* ---- Focus trap ------------------------------------------- */
  /* The overlay is aria-modal="true" so focus must not escape into
     the chrome behind it. On open we stash the previously-focused
     element, move focus into the overlay, and sentinel spans at
     the top/bottom boundary redirect Tab wrapping. On close the
     previous focus is restored.                                   */
  let overlayEl = $state<HTMLElement | null>(null);
  let closeBtn = $state<HTMLElement | null>(null);
  let previousFocus: Element | null = null;

  $effect(() => {
    if (store.player.isExpanded && overlayEl) {
      previousFocus = document.activeElement;
      // Tick delay so the DOM has rendered before we move focus.
      requestAnimationFrame(() => closeBtn?.focus());
      return () => {
        if (previousFocus instanceof HTMLElement) previousFocus.focus();
      };
    }
  });

  function trapFocus(direction: 'first' | 'last') {
    if (!overlayEl) return;
    const focusable = overlayEl.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    // Skip sentinels (first and last children with tabindex="0" and class .focus-sentinel)
    const targets = Array.from(focusable).filter(el => !el.classList.contains('focus-sentinel'));
    if (targets.length === 0) return;
    if (direction === 'first') targets[0].focus();
    else targets[targets.length - 1].focus();
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if store.player.isExpanded && store.player.current}
  {@const t = store.player.current}
  <div class="overlay" role="dialog" aria-modal="true" aria-label="Now playing" bind:this={overlayEl}>
    <!-- Focus sentinel: catches Shift+Tab at the top boundary -->
    <button class="focus-sentinel btn-reset" type="button" onfocus={() => trapFocus('last')} aria-label="Focus sentinel"></button>
    <button class="close" onclick={close} aria-label="Minimize now playing" bind:this={closeBtn}>
      <Icon name="chevron-down" size={24} />
    </button>
    <button
      class="queue-btn"
      onclick={openQueue}
      aria-label={store.queue.length > 0
        ? `Open queue, ${store.queue.length} ${store.queue.length === 1 ? 'track' : 'tracks'}`
        : 'Open queue'}
    >
      <Icon name="list-music" size={22} />
      {#if store.queue.length > 0}<span class="queue-badge" aria-hidden="true">{store.queue.length}</span>{/if}
    </button>

    <!-- Content zone — scrolls vertically when artwork + title can't
         fit the viewport. The overlay-controls zone below stays put. -->
    <div class="overlay-content">
      <div class="art" style:view-transition-name="now-playing-art">
        {#if t.thumbnailUrl}
          <img src={t.thumbnailUrl} alt="" />
        {:else}
          <div class="art-placeholder"></div>
        {/if}
      </div>

      <div class="meta">
        {#key t.videoId}
          <div class="title">{t.title}</div>
        {/key}
        <div class="meta-strip">
          <span class="author">{t.author}</span>
          {#if t.isLive}
            <span class="dot">·</span>
            <LivePill size="sm" />
          {:else}
            <span class="dot">·</span>
            <span>{formatDuration(t.durationSeconds)}</span>
            {#if t.viewCount != null}
              <span class="dot">·</span>
              <span>{formatViewCount(t.viewCount)} views</span>
            {/if}
            {#if t.bitrate != null}
              <span class="dot">·</span>
              <span>{formatBitrate(t.bitrate)}</span>
            {/if}
          {/if}
        </div>
        {#if !t.isLive}
          <div class="quality-row">
            <span class="quality-label">Quality</span>
            <div class="seg" role="radiogroup" aria-label="Quality">
              <button
                class="seg-opt"
                class:active={t.qualityTier === 'hi'}
                aria-pressed={t.qualityTier === 'hi'}
                onclick={() => store.switchQuality('hi')}
              >Hi</button>
              <button
                class="seg-opt"
                class:active={t.qualityTier === 'low'}
                aria-pressed={t.qualityTier === 'low'}
                onclick={() => store.switchQuality('low')}
              >Low</button>
            </div>
          </div>
        {/if}
      </div>
    </div>

    <!-- Controls zone — sticky bottom, always reachable. Scrubber lives
         here paired with transport (Apple Music / Spotify pattern). -->
    <div class="overlay-controls">
      {#if !t.isLive}
        <div class="scrubber" style="--progress: {liveDur ? (livePos / liveDur) * 100 : 0}%">
          <input
            type="range"
            min="0"
            max={liveDur || t.durationSeconds}
            step="1"
            value={livePos}
            oninput={onScrub}
            aria-label="Seek"
            aria-valuetext="{formatDuration(livePos)} of {formatDuration(liveDur || t.durationSeconds)}"
          />
          <div class="times">
            <span>{formatDuration(livePos)}</span>
            <span>{formatDuration(liveDur || t.durationSeconds)}</span>
          </div>
        </div>
      {/if}

      <div class="transport">
      <button
        class="mode"
        class:active={store.player.shuffle}
        onclick={() => store.toggleShuffle()}
        aria-label={store.player.shuffle ? 'Shuffle on' : 'Shuffle off'}
        aria-pressed={store.player.shuffle}
      >
        <Icon name="shuffle" size={24} />
      </button>

      {#if !t.isLive}
        <button class="ctrl ctrl-prev" onclick={restartTrack} aria-label="Restart track">
          <Icon name="skip-back" size={30} />
        </button>
      {/if}

      <button class="ctrl" onclick={togglePlayPause} aria-label={livePaused ? 'Play' : 'Pause'}>
        {#if livePaused}
          <Icon name="play" size={36} />
        {:else}
          <Icon name="pause" size={36} />
        {/if}
      </button>

      <button class="ctrl ctrl-next" onclick={() => store.next()} aria-label="Next track">
        <Icon name="skip-forward" size={30} />
      </button>

      <button
        class="mode"
        class:active={store.player.repeat !== 'off'}
        onclick={() => store.cycleRepeat()}
        aria-label={'Repeat ' + store.player.repeat}
      >
        {#if store.player.repeat === 'one'}
          <Icon name="repeat-1" size={24} />
        {:else}
          <Icon name="repeat" size={24} />
        {/if}
      </button>

      <!-- AirPlay: opens Safari's system picker via the shared playerControls
           method (the <audio> element lives in Player.svelte). Active/route
           state is owned there; this surface is intentionally stateless.
           store.player.airplayCapable gates it so the button never shows when
           AirPlay is unsupported, no target is available, or the track is live. -->
      {#if store.player.airplayCapable}
        <button
          class="mode"
          aria-label="AirPlay"
          onclick={() => playerControls.current?.showPlaybackTargetPicker?.()}
        >
          <Icon name="airplay" size={24} />
        </button>
      {/if}
      </div>
    </div>
    <!-- Focus sentinel: catches Tab at the bottom boundary -->
    <button class="focus-sentinel btn-reset" type="button" onfocus={() => trapFocus('first')} aria-label="Focus sentinel"></button>
  </div>
{/if}

<style>
  /* Three-zone overlay shape: chrome / content / controls.
     - Chrome (close, queue) is position:absolute, outside grid flow.
     - Content (artwork, title, meta) takes 1fr and scrolls if its
       intrinsic height exceeds the row.
     - Controls (scrubber, transport) take auto height, stay at bottom,
       always visible regardless of content scroll position.
     This mirrors the main app shell (nav / main / player capsule). */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 200;
    display: grid;
    grid-template-rows: 1fr auto;
    /* Glass over the artwork backdrop (already fixed beneath everything).
       Lighter scrim + reduced blur than the previous 0.45 / 40px — the
       chromatic wash is the signature of this view and was getting
       muddied. Text on top is held by --text-shadow-chromatic on .title
       and dark-tinted glass on the meta-strip. */
    background: rgba(7, 9, 12, 0.32);
    backdrop-filter: blur(28px) saturate(180%);
    -webkit-backdrop-filter: blur(28px) saturate(180%);
    animation: fade-in var(--dur-base) var(--ease);
  }
  /* Invisible tabbable sentinels for focus wrapping. */
  .focus-sentinel {
    position: absolute;
    width: 1px; height: 1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
  }

  .overlay-content {
    /* `safe center` centres when content fits the row but falls back
       to flex-start when it overflows — so the top of the artwork stays
       reachable rather than clipping. min-height: 0 lets the grid 1fr
       row actually shrink (flex children inside grid need this). */
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: safe center;
    gap: var(--container-gap);
    padding:
      var(--container-pad-block-start)
      var(--container-pad-inline)
      var(--s-4);
  }

  .overlay-controls {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--s-4);
    padding:
      var(--s-4)
      var(--container-pad-inline)
      var(--container-pad-block-end);
  }

  /* Close / minimise button — top-right corner */
  .close {
    position: absolute;
    top: var(--s-5);
    right: var(--s-5);
    width: 44px;
    height: 44px;
    padding: 0;
    border-radius: 50%;
    background: var(--glass-2);
    border: 1px solid var(--hairline-soft);
    display: grid;
    place-items: center;
    color: var(--ink);
    box-shadow: none;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
  .close:hover:not(:disabled) {
    background: var(--glass-3);
    transform: scale(1.06);
  }

  /* Queue button — top-left mirror of close. Badge shows queue length. */
  .queue-btn {
    position: absolute;
    top: var(--s-5);
    left: var(--s-5);
    height: 44px;
    min-width: 44px;
    padding: 0 var(--s-3);
    border-radius: 22px;
    background: var(--glass-2);
    border: 1px solid var(--hairline-soft);
    display: inline-flex;
    align-items: center;
    gap: var(--s-2);
    color: var(--ink);
    box-shadow: none;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
  .queue-btn:hover:not(:disabled) {
    background: var(--glass-3);
    transform: scale(1.04);
  }
  .queue-badge {
    font-size: var(--t-xs);
    font-variant-numeric: tabular-nums;
    color: var(--ink-soft);
    letter-spacing: 0.02em;
  }

  /* Hero artwork — centred, large, with a deep shadow.
     `45vh` so the 3-line title + meta-strip fit alongside the artwork
     in the content row at 900px-tall viewports without scrolling. The
     480px cap still applies on taller displays (1080+ kicks the cap). */
  .art {
    width: min(45vh, 480px);
    height: min(45vh, 480px);
    border-radius: var(--r-xl);
    overflow: hidden;
    box-shadow:
      var(--inner-top-highlight),
      0 40px 100px rgba(0, 0, 0, 0.6);
    border: 1px solid var(--hairline);
    flex-shrink: 0;
  }
  .art img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .art-placeholder {
    width: 100%;
    height: 100%;
    background: linear-gradient(135deg, var(--glass-3), var(--glass-1));
  }

  /* Track info */
  .meta {
    text-align: center;
    max-width: min(90vw, 600px);
    width: 100%;
    /* Ensure flex/grid children don't blow this past its parent on narrow
       viewports. The hero artwork sets the overall width budget. */
    min-width: 0;
  }
  .title {
    font-family: var(--font-sans);
    font-size: clamp(24px, 4.5vw, 52px);
    line-height: 1.08;
    letter-spacing: -0.02em;
    color: var(--ink);
    margin-bottom: var(--s-2);
    /* Wrap to a max of 3 lines and centre-balance the break for editorial
       feel. 3 lines fits even very long YouTube titles like
       "Track Name (Official Video) (4K Remaster)" without ellipsis. */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    /* Force breaks on long unbreakable strings (e.g. URL-style titles or
       no-space lofi-channel names) so the title never exceeds .meta. */
    overflow-wrap: anywhere;
    word-break: break-word;
    max-width: 100%;
    text-wrap: balance;
    /* Sits directly on the chromatic wash — hold the glyph edge. */
    text-shadow: var(--text-shadow-chromatic);
  }
  /* Metadata strip — author · duration · views · bitrate. The byline used
     to be a separate larger row above; folding it into the strip cuts a
     stacked element from the meta block and matches the Video detail
     pattern. Author stays visually anchored via full-ink weight 500. */
  .meta-strip {
    display: inline-flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: var(--s-2);
    align-items: center;
    margin-top: var(--s-3);
    padding: 6px 14px;
    border-radius: var(--r-pill);
    background: var(--glass-2);
    border: 1px solid var(--hairline-soft);
    font-size: var(--t-sm);
    color: var(--ink-soft);
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.005em;
    backdrop-filter: blur(20px) saturate(170%);
    -webkit-backdrop-filter: blur(20px) saturate(170%);
  }
  .meta-strip .author { color: var(--ink); font-weight: 500; }
  .meta-strip .dot { color: var(--ink-faint); }

  /* Scrubber track */
  .scrubber {
    width: min(80vw, 560px);
    display: flex;
    flex-direction: column;
    gap: var(--s-1);
  }
  .scrubber input {
    width: 100%;
    height: 44px;
    background: transparent;
    cursor: pointer;
    /* The default range thumb + track render centred within the input box,
       so a 44px input gives a humane touch hit zone while keeping the
       visible track itself delicate. WCAG 2.5.5 / Apple HIG min 44px. */
  }
  .times {
    display: flex;
    justify-content: space-between;
    font-size: var(--t-xs);
    color: var(--ink-faint);
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.02em;
  }

  /* Transport controls */
  .transport {
    display: flex;
    align-items: center;
    gap: var(--s-5);
  }

  /* Shared transport button reset */
  .transport button {
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }

  /* Mode buttons (shuffle / repeat) — sized for the full-bleed view */
  .transport .mode {
    width: 48px;
    height: 48px;
    padding: 0;
    border-radius: 50%;
    background: transparent;
    border: 1px solid transparent;
    color: var(--ink-muted);
    display: grid;
    place-items: center;
    box-shadow: none;
  }
  .transport .mode:hover:not(:disabled) {
    color: var(--ink);
    background: var(--glass-2);
  }
  .transport .mode.active {
    color: var(--accent);
    background: var(--glass-2);
    border-color: var(--hairline);
  }

  /* Primary play/pause button — 72px so it actually owns this view */
  .transport .ctrl {
    width: 72px;
    height: 72px;
    padding: 0;
    border-radius: 50%;
    background: var(--ink);
    border: none;
    color: #0b0d11;
    display: grid;
    place-items: center;
    box-shadow: 0 10px 30px rgba(255, 255, 255, 0.22);
  }
  .transport .ctrl:hover:not(:disabled) {
    background: white;
    transform: scale(1.06);
  }

  /* Next button — clearly secondary to play but bigger than the modes */
  .transport .ctrl-next,
  .transport .ctrl-prev {
    width: 56px;
    height: 56px;
    background: var(--glass-2);
    border: 1px solid var(--hairline-soft);
    color: var(--ink);
    box-shadow: none;
  }
  .transport .ctrl-next:hover:not(:disabled),
  .transport .ctrl-prev:hover:not(:disabled) {
    background: var(--glass-3);
    transform: scale(1.05);
  }

  /* Quality segmented control */
  .quality-row {
    display: flex;
    align-items: center;
    gap: var(--s-3);
    margin-top: var(--s-3);
    justify-content: center;
  }
  .quality-label {
    color: var(--ink-muted);
    font-size: var(--t-sm);
    letter-spacing: 0.02em;
  }
  .seg {
    display: inline-flex;
    background: var(--glass-2);
    border: 1px solid var(--hairline-soft);
    border-radius: var(--r-pill);
    padding: 3px;
    gap: 2px;
  }
  .seg-opt {
    padding: 4px 14px;
    border: none;
    background: transparent;
    border-radius: var(--r-pill);
    color: var(--ink-soft);
    font-size: var(--t-sm);
    cursor: pointer;
  }
  .seg-opt.active {
    background: var(--ink);
    color: #0b0d11;
  }

  /* Mobile: tighter layout. Padding moves to the zone rules; the grid
     itself stays the same (1fr auto) so the chrome / content / controls
     shape is preserved at every viewport. */
  @media (max-width: 720px) {
    .overlay-content {
      padding: var(--s-6) var(--s-4) var(--s-3);
      gap: var(--s-4);
    }
    .overlay-controls {
      padding: var(--s-3) var(--s-4) var(--s-6);
      gap: var(--s-3);
    }
    .art {
      width: min(72vw, 360px);
      height: min(72vw, 360px);
    }
    .transport {
      gap: var(--s-4);
    }
  }
</style>
