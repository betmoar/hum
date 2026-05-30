<script lang="ts">
  import { untrack } from 'svelte';
  import { store, playerControls } from './lib/store.svelte';
  import { router } from './routes.svelte';
  import Setup from './components/Setup.svelte';
  import Player from './components/Player.svelte';
  import NowPlaying from './components/NowPlaying.svelte';
  import Toast from './components/Toast.svelte';
  import Icon from './components/Icon.svelte';
  import HumMark from './components/HumMark.svelte';
  import { applyArtHue } from './lib/artHue.svelte';

  let mainEl = $state<HTMLElement | null>(null);
  let isFirstMount = true;
  $effect(() => {
    void router.path; // subscribe to path changes
    if (isFirstMount) { isFirstMount = false; return; }
    mainEl?.focus({ preventScroll: true });
  });

  function go(path: string) {
    router.navigate(path);
  }

  // The artwork-tinted backdrop is the visual signature of the app.
  // We swap two layers and crossfade for a smooth Apple Music-style
  // transition when the playing track changes.
  //
  // If nothing is playing but there's a queued track, use its artwork as a
  // faded preview backdrop so the chromatic signature is always visible.
  let backdropUrl = $derived(
    store.player.current?.thumbnailUrl
    ?? store.queue[0]?.thumbnailUrl
    ?? ''
  );
  let layerA = $state('');
  let layerB = $state('');
  let showB = $state(false);

  // Effect must only re-run when backdropUrl changes; the layer/showB writes
  // would otherwise feedback-loop (effect_update_depth_exceeded). Use
  // untrack() so the reads inside don't subscribe.
  $effect(() => {
    const url = backdropUrl;
    const wasB = untrack(() => showB);
    if (!url) {
      // Fade both layers out — the static gradient under #app shows through.
      layerA = '';
      layerB = '';
      return;
    }
    if (wasB) {
      layerA = url;
      showB = false;
    } else {
      layerB = url;
      showB = true;
    }
  });

  // Apply chromatic art hue to :root so glass surfaces pick up the
  // album's dominant colour at 5-8% mix.
  $effect(() => {
    applyArtHue(backdropUrl || null);
  });

  // ---- Help overlay state ------------------------------------
  let showHelp = $state(false);

  // ---- Global keyboard handler --------------------------------
  // Installed on window in an $effect so it only runs client-side (not SSR).
  // Bails early for input elements and modifier keys to avoid stealing typing
  // or shadowing browser shortcuts.
  $effect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const c = playerControls.current;
      switch (e.key) {
        case ' ': case 'k': case 'K':
          e.preventDefault(); c?.toggle(); return;
        case 'ArrowRight':
          e.preventDefault(); c?.seekBy(e.shiftKey ? 30 : 5); return;
        case 'ArrowLeft':
          e.preventDefault(); c?.seekBy(e.shiftKey ? -30 : -5); return;
        case 'l': case 'L':
          e.preventDefault(); c?.seekBy(10); return;
        case 'j': case 'J':
          e.preventDefault(); c?.seekBy(-10); return;
        case 'n': case 'N':
          e.preventDefault(); store.next(); return;
        case 'm': case 'M':
          e.preventDefault(); c?.toggleMute(); return;
        case '/':
          e.preventDefault();
          if (router.path !== '/') router.navigate('/');
          setTimeout(() => {
            const i = document.querySelector('input[type="search"]') as HTMLInputElement | null;
            i?.focus();
          }, 50);
          return;
        case '?':
          e.preventDefault(); showHelp = !showHelp; return;
        case 'Escape':
          // NowPlaying overlay's own svelte:window handler wins first via
          // stopPropagation when the overlay is open; this fallback handles
          // the help overlay only.
          if (showHelp) { showHelp = false; e.preventDefault(); }
          return;
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
</script>

{#if !store.settings.bearerToken}
  <Setup />
{:else}
  <!-- Artwork-tinted backdrop. Two layers crossfade on track change.
       The 'preview' modifier dims the layers when showing queue art
       before a track is playing — so the backdrop is always visible
       but clearly not active-playback state. -->
  <div
    class="art-stage"
    class:preview={!store.player.current && store.queue.length > 0}
    class:dampened={router.path === '/queue' && !store.player.isExpanded}
    aria-hidden="true"
  >
    <!-- Ambient layer: always present. Carries a soft dual-radial wash
         in the current --art-hue so empty/no-track states still feel
         alive ("living glass"). Occluded when real artwork layers are
         at full opacity. -->
    <div class="art-ambient"></div>
    <div
      class="art-layer"
      class:visible={!showB && !!layerA}
      style:background-image={layerA ? `url("${layerA}")` : 'none'}
    ></div>
    <div
      class="art-layer"
      class:visible={showB && !!layerB}
      style:background-image={layerB ? `url("${layerB}")` : 'none'}
    ></div>
    <div class="art-wash"></div>
  </div>

  <!-- Chrome (nav, main, Player) stays MOUNTED when NowPlaying is expanded so
       the <audio> element survives the transition without re-fetching the URL
       or hiccupping playback. We hide visually + suppress interaction instead.
       The mini-player art's view-transition-name is also removed while expanded
       so only one element claims the morph target at a time. -->
  <div class="chrome" class:hidden={store.player.isExpanded}>
    <nav class="glass-nav">
      <div class="brand">
        <span class="brand-mark"><HumMark size={28} /></span>
        <span class="brand-name">Hum</span>
      </div>
      <div class="nav-links">
        <a href="#/" class:active={router.path === '/'} onclick={(e) => { e.preventDefault(); go('/'); }}>
          <Icon name="search" size={22} />
          <span class="label">Search</span>
        </a>
        <a href="#/queue" class:active={router.path === '/queue'} onclick={(e) => { e.preventDefault(); go('/queue'); }}>
          <Icon name="list-music" size={22} />
          <span class="label">Queue{#if store.queue.length > 0}<span class="queue-count"> {store.queue.length}</span>{/if}</span>
        </a>
        <a href="#/radio" class:active={router.path === '/radio'} onclick={(e) => { e.preventDefault(); go('/radio'); }}>
          <Icon name="radio" size={22} />
          <span class="label">Radio</span>
        </a>
        <a href="#/settings" class:active={router.path === '/settings'} onclick={(e) => { e.preventDefault(); go('/settings'); }}>
          <Icon name="settings" size={22} />
          <span class="label">Settings</span>
        </a>
      </div>
    </nav>

    <main bind:this={mainEl} tabindex="-1">
      {#if router.match}
        {@const Page = router.match.component}
        {#key router.path}
          <div class="route-fade">
            <Page {...router.match.params} />
          </div>
        {/key}
      {/if}
    </main>

    <Player />
  </div>

  <NowPlaying />
  <Toast />

  {#if showHelp}
    <div class="help-overlay">
      <button class="help-overlay-backdrop btn-reset" onclick={() => showHelp = false} aria-label="Close help overlay"></button>
      <div class="help-card" role="dialog" aria-label="Keyboard shortcuts" tabindex="-1">
        <h2>Keyboard shortcuts</h2>
        <dl>
          <dt><kbd>Space</kbd> / <kbd>K</kbd></dt><dd>Play / pause</dd>
          <dt><kbd>←</kbd> / <kbd>→</kbd></dt><dd>Seek ±5s</dd>
          <dt><kbd>Shift</kbd>+<kbd>←</kbd> / <kbd>→</kbd></dt><dd>Seek ±30s</dd>
          <dt><kbd>J</kbd> / <kbd>L</kbd></dt><dd>Seek ±10s</dd>
          <dt><kbd>N</kbd></dt><dd>Next track</dd>
          <dt><kbd>M</kbd></dt><dd>Mute / unmute</dd>
          <dt><kbd>/</kbd></dt><dd>Focus search</dd>
          <dt><kbd>?</kbd></dt><dd>Toggle this help</dd>
          <dt><kbd>Esc</kbd></dt><dd>Close help</dd>
        </dl>
        <p class="hint">Press <kbd>?</kbd> any time to reopen.</p>
      </div>
    </div>
  {/if}
{/if}

<style>
  /* ---- Artwork backdrop -------------------------------------- */
  .art-stage {
    position: fixed;
    inset: 0;
    z-index: -1;
    pointer-events: none;
    overflow: hidden;
  }
  /* Ambient layer — quiet dual-radial in the current --art-hue.
     Sub-2% drift on a long period keeps the surface feeling alive
     even when no artwork is loaded. Always rendered; occluded when
     a real .art-layer is visible at opacity 1. */
  .art-ambient {
    position: absolute;
    inset: -5%;
    background:
      radial-gradient(
        ellipse 80% 60% at 28% 32%,
        hsla(var(--art-hue), var(--art-sat), 40%, 0.22) 0%,
        transparent 60%
      ),
      radial-gradient(
        ellipse 60% 70% at 72% 70%,
        hsla(var(--art-hue), var(--art-sat), 35%, 0.16) 0%,
        transparent 62%
      );
    transform: translate3d(0, 0, 0) scale(1);
    will-change: transform;
  }
  .art-layer {
    position: absolute;
    /* Overscale so the blur edges never show (and so drift has slack). */
    inset: -10%;
    background-size: cover;
    background-position: center;
    /* Less blur, more saturation, no brightness multiplier.
       Apple Music lets the colour bloom; the old value was
       tinting everything grey with brightness(0.85).             */
    filter: blur(60px) saturate(220%);
    transform: scale(1.2) translate3d(0, 0, 0);
    opacity: 0;
    transition: opacity var(--dur-bg) var(--ease);
    will-change: opacity, transform;
  }
  .art-layer.visible { opacity: 1; }
  /* When showing queue-preview art (no active track), dim layers so it reads
     as a preview, not an active-playback backdrop. */
  .art-stage.preview .art-layer.visible { opacity: 0.5; }
  /* On the /queue route the cards are the subject, not the backdrop —
     dampen the wash so it stops competing with the now-playing hero card
     and the queued rows for attention. Player-active and expanded views
     keep full wash because there the artwork IS the subject. */
  .art-stage.dampened .art-layer.visible { opacity: 0.55; }
  .art-stage.dampened.preview .art-layer.visible { opacity: 0.3; }
  /* Vignette wash: dark at the edges, almost nothing at centre.
     Apple Music's wash is ~25-35% darken at edges and near-zero
     in the centre. The old dual-gradient was inverted — it was
     darkening the centre and washing out the colour bloom.       */
  .art-wash {
    position: absolute;
    inset: 0;
    background:
      radial-gradient(
        circle at 50% 40%,
        transparent 0%,
        transparent 35%,
        rgba(7, 9, 12, 0.45) 100%
      );
    transform: scale(1);
    will-change: transform, opacity;
  }

  /* Living glass — slow, subliminal motion. Sub-2% positional range,
     long unaligned periods (60s / 80s / 22s) so the loops never feel
     like loops. Gated on prefers-reduced-motion. */
  @media (prefers-reduced-motion: no-preference) {
    .art-layer {
      animation: art-drift 60s linear infinite;
    }
    .art-ambient {
      animation: ambient-drift 80s ease-in-out infinite;
    }
    .art-wash {
      animation: wash-breathe 22s ease-in-out infinite;
    }
  }
  @keyframes art-drift {
    0%   { transform: scale(1.20) translate3d(0%, 0%, 0); }
    25%  { transform: scale(1.22) translate3d(-1.4%, -1%, 0); }
    50%  { transform: scale(1.21) translate3d(1%, -1.4%, 0); }
    75%  { transform: scale(1.23) translate3d(-1%, 1.4%, 0); }
    100% { transform: scale(1.20) translate3d(0%, 0%, 0); }
  }
  @keyframes ambient-drift {
    0%, 100% { transform: translate3d(0%, 0%, 0) scale(1.00); }
    50%      { transform: translate3d(1.5%, -1.2%, 0) scale(1.04); }
  }
  @keyframes wash-breathe {
    0%, 100% { opacity: 1;    transform: scale(1.00); }
    50%      { opacity: 0.92; transform: scale(1.03); }
  }

  /* ---- Chrome visibility gate -------------------------------- */
  /* When NowPlaying is expanded, hide the entire chrome stack
     (nav + main + Player) visually but keep it mounted so the
     <audio> element survives without re-fetching the stream. */
  .chrome.hidden {
    visibility: hidden;
    pointer-events: none;
  }

  /* ---- Top navigation --------------------------------------- */
  .glass-nav {
    position: sticky;
    top: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s-5);
    padding: var(--s-3) var(--s-6);
    height: var(--nav-h);
    background: rgba(10, 12, 16, 0.55);
    border-bottom: 1px solid var(--hairline);
    backdrop-filter: blur(40px) saturate(180%);
    -webkit-backdrop-filter: blur(40px) saturate(180%);
  }

  .brand {
    display: flex;
    align-items: center;
    gap: var(--s-3);
  }
  /* Flat coral mark — no background plate, no shadow, no gradient.
     Color inherits to the SVG via currentColor. */
  .brand-mark {
    color: var(--accent);
    display: inline-block;
    vertical-align: middle;
  }
  .brand-name {
    font-family: var(--font-sans);
    font-size: var(--t-xl);
    letter-spacing: -0.01em;
  }

  .nav-links {
    display: flex;
    align-items: center;
    gap: var(--s-4);
  }
  .nav-links a {
    display: inline-flex;
    align-items: baseline;
    gap: 5px;
    color: var(--ink-soft);
    padding: 4px 0;
    font-size: var(--t-sm);
    font-weight: 500;
    letter-spacing: -0.005em;
    /* Underline drawn as box-shadow so it doesn't shift layout */
    box-shadow: inset 0 -2px 0 transparent;
    transition: color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
  }
  .nav-links a:hover { color: var(--ink); }
  .nav-links a.active {
    color: var(--ink);
    box-shadow: inset 0 -2px 0 var(--accent);
  }
  /* Icons are mobile-only; desktop keeps the typographic underline-on-active
     nav so this change doesn't disturb the desktop design. */
  .nav-links a :global(svg) { display: none; }
  .queue-count {
    color: var(--ink-faint);
    font-size: var(--t-xs);
    font-weight: 400;
  }

  /* ---- Page area -------------------------------------------- */
  main {
    padding-bottom: calc(var(--player-h) + var(--s-7));
    min-height: calc(100vh - var(--nav-h));
  }
  .route-fade {
    animation: fade-in var(--dur-base) var(--ease);
  }

  @media (max-width: 640px) {
    .glass-nav { padding: var(--s-3) var(--s-4); }
    .brand-name { display: none; }
  }
  @media (max-width: 480px) {
    .glass-nav {
      flex-wrap: wrap;
      gap: var(--s-2);
    }
    .nav-links a {
      padding: 8px 12px;
      font-size: var(--t-xs);
    }
  }

  /* ---- Mobile bottom tab bar -------------------------------- */
  /* On small screens convert the top nav into a sticky bottom tab bar,
     matching native mobile-app idioms. The brand mark is hidden — only
     the route links are shown in the bar. */
  @media (max-width: 720px) {
    .glass-nav {
      position: fixed;
      top: auto;
      bottom: 0;
      left: 0;
      right: 0;
      padding: var(--s-2) var(--s-2);
      height: var(--tab-h);
      padding-bottom: env(safe-area-inset-bottom, 0px);
      border-top: 1px solid var(--hairline);
      border-bottom: none;
      background: rgba(10, 12, 16, 0.82);
      backdrop-filter: blur(60px) saturate(180%);
      -webkit-backdrop-filter: blur(60px) saturate(180%);
      justify-content: space-around;
      z-index: 15;
    }
    .glass-nav .brand { display: none; }
    .nav-links {
      width: 100%;
      justify-content: space-around;
      gap: 0;
    }
    .nav-links a {
      flex: 1;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 2px;
      text-align: center;
      padding: 6px 8px;
      font-size: var(--t-xs);
      /* Remove underline indicator — use pill highlight instead */
      box-shadow: none;
      border-radius: var(--r-md);
      color: var(--ink-muted);
    }
    /* Show icons on mobile, stacked above the label */
    .nav-links a :global(svg) {
      display: block;
      color: currentColor;
    }
    .nav-links a .label {
      letter-spacing: 0.01em;
      font-weight: 500;
    }
    .nav-links a.active {
      color: var(--ink);
      background: var(--glass-2);
      box-shadow: none;
    }
    .nav-links a.active :global(svg) {
      color: var(--accent);
    }
    /* Push content below top nav (now removed) and above tab bar + player */
    main {
      padding-top: env(safe-area-inset-top, 0px);
      padding-bottom: calc(var(--player-h) + var(--tab-h) + var(--s-5) + var(--tab-h));
    }
  }

  /* ---- Help overlay ----------------------------------------- */
  .help-overlay {
    position: fixed;
    inset: 0;
    z-index: 100;
    display: grid;
    place-items: center;
    background: rgba(7, 9, 12, 0.55);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    animation: fade-in var(--dur-base) var(--ease);
  }
  .help-overlay-backdrop {
    position: absolute;
    inset: 0;
    cursor: default;
    z-index: 1;
  }
  .help-card {
    position: relative;
    z-index: 2;
    background: var(--glass-4);
    backdrop-filter: blur(40px) saturate(180%);
    -webkit-backdrop-filter: blur(40px) saturate(180%);
    border: 1px solid var(--hairline);
    border-radius: var(--r-xl);
    box-shadow: var(--inner-top-highlight), 0 40px 100px rgba(0, 0, 0, 0.6);
    padding: var(--s-6);
    max-width: 480px;
    width: calc(100% - var(--s-6) * 2);
  }
  .help-card h2 {
    font-family: var(--font-sans);
    font-size: var(--t-xl);
    font-weight: 500;
    letter-spacing: -0.01em;
    margin: 0 0 var(--s-5);
  }
  .help-card dl {
    margin: 0;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--s-3) var(--s-5);
    font-size: var(--t-sm);
  }
  .help-card dt {
    color: var(--ink-soft);
    white-space: nowrap;
  }
  .help-card dd {
    margin: 0;
    color: var(--ink);
  }
  .help-card kbd {
    display: inline-block;
    padding: 2px 8px;
    border: 1px solid var(--hairline);
    border-radius: 6px;
    background: var(--glass-2);
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: var(--t-xs);
    color: var(--ink);
    margin: 0 2px;
  }
  .help-card .hint {
    margin: var(--s-5) 0 0;
    color: var(--ink-muted);
    font-size: var(--t-sm);
  }
</style>
