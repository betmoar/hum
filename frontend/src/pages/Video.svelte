<script lang="ts">
  import { api } from '../lib/api';
  import { store } from '../lib/store.svelte';
  import { formatDuration, formatViewCount } from '../lib/format';
  import Spinner from '../components/Spinner.svelte';
  import Icon from '../components/Icon.svelte';
  import LivePill from '../components/LivePill.svelte';
  import type { Quality, VideoDetails } from '../lib/types';

  type Props = { id: string };
  let { id }: Props = $props();

  let loading = $state(true);
  let error = $state<string | null>(null);
  let details = $state<VideoDetails | null>(null);

  $effect(() => {
    let cancelled = false;
    loading = true;
    error = null;
    api
      .video(id)
      .then((d) => { if (!cancelled) details = d; })
      .catch((e) => {
        if (!cancelled) error = e instanceof Error ? e.message : 'Load failed';
      })
      .finally(() => { if (!cancelled) loading = false; });
    return () => { cancelled = true; };
  });

  function playNow() {
    if (!details) return;
    store.playNowAtTier(details, store.settings.defaultQuality);
  }
  function playAtTier(tier: Quality) {
    if (!details) return;
    store.playNowAtTier(details, tier);
  }
  function enqueue() {
    if (!details) return;
    void store.enqueueById(details.video_id);
  }
  function playNextAction() {
    if (!details) return;
    void store.playNextById(details.video_id);
  }
</script>

<section>
  {#if loading}
    <Spinner />
  {:else if error}
    <p class="error">{error}</p>
  {:else if details}
    <header class="hero">
      <div class="art-frame">
        {#if details.thumbnail_url}
          <img src={details.thumbnail_url} alt="" />
        {/if}
      </div>
      <div class="info">
        <p class="eyebrow">Now viewing</p>
        <h1>{details.title}</h1>
        <p class="byline">
          <span class="author">{details.author}</span>
          {#if details.is_live}
            <span class="dot">·</span>
            <LivePill />
          {:else}
            <span class="dot">·</span>
            <span>{formatDuration(details.duration_seconds)}</span>
            {#if details.view_count}
              <span class="dot">·</span>
              <span>{formatViewCount(details.view_count)} views</span>
            {/if}
          {/if}
        </p>
        <div class="actions">
          <button class="primary" onclick={playNow}>
            <Icon name="play" size={18} />
            Play now
          </button>
          <button onclick={playNextAction}>
            <Icon name="skip-forward" size={18} />
            Play next
          </button>
          <button onclick={enqueue}>
            <Icon name="list-plus" size={18} />
            Add to queue
          </button>
        </div>
      </div>
    </header>

    {#if !details.is_live}
      <h3 class="section-h">Quality</h3>
      {#if details.audio_formats.length > 0}
        <div class="tier-chips">
          <button
            class="tier-chip"
            class:active={store.player.current?.videoId === details.video_id && store.player.current?.qualityTier === 'hi'}
            onclick={() => playAtTier('hi')}
          >Hi</button>
          <button
            class="tier-chip"
            class:active={store.player.current?.videoId === details.video_id && store.player.current?.qualityTier === 'low'}
            onclick={() => playAtTier('low')}
          >Low</button>
        </div>
        <p class="tier-caption">Hi picks the best available codec for your browser. Low picks the same codec at the lowest available bitrate.</p>
      {/if}
    {/if}
  {/if}
</section>

<style>
  section {
    padding: var(--container-pad-block-start) var(--container-pad-inline) var(--container-pad-block-end);
    max-width: var(--container-max);
    margin: 0 auto;
  }
  .hero {
    display: grid;
    grid-template-columns: minmax(220px, 320px) 1fr;
    gap: var(--s-6);
    align-items: end;
    margin-bottom: var(--s-7);
  }
  .art-frame {
    aspect-ratio: 1 / 1;
    width: 100%;
    border-radius: var(--r-xl);
    overflow: hidden;
    border: 1px solid var(--hairline);
    box-shadow:
      var(--inner-top-highlight),
      0 30px 60px rgba(0, 0, 0, 0.55);
    background: var(--glass-2);
  }
  .art-frame img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  h1 {
    font-family: var(--font-sans);
    font-size: clamp(32px, 5vw, 56px);
    line-height: 1.05;
    margin-bottom: var(--s-3);
    /* Display serif sits over the chromatic wash — hold the glyph edge. */
    text-shadow: var(--text-shadow-chromatic);
  }
  .byline {
    color: var(--ink-soft);
    font-size: var(--t-lg);
    font-variant-numeric: tabular-nums;
    margin-bottom: var(--s-5);
    display: flex;
    flex-wrap: wrap;
    gap: var(--s-2);
    align-items: center;
  }
  .byline .author { color: var(--ink); font-weight: 500; }
  .byline .dot { color: var(--ink-faint); }
  .byline span:not(.author):not(.dot) { font-variant-numeric: tabular-nums; }

  .actions {
    display: flex;
    gap: var(--s-3);
    flex-wrap: wrap;
  }
  .actions button {
    display: inline-flex;
    align-items: center;
    gap: var(--s-2);
    padding: 12px 22px;
    font-size: var(--t-base);
  }

  .section-h {
    font-size: var(--t-xl);
    margin-bottom: var(--s-4);
    color: var(--ink-soft);
  }

  .tier-chips {
    display: flex;
    gap: var(--s-3);
  }
  .tier-chip {
    padding: 10px 22px;
    background: var(--glass-2);
    border: 1px solid var(--hairline);
    border-radius: var(--r-pill);
    font-size: var(--t-base);
    color: var(--ink-soft);
    backdrop-filter: blur(30px) saturate(170%);
    -webkit-backdrop-filter: blur(30px) saturate(170%);
  }
  .tier-chip:hover:not(:disabled) {
    background: var(--glass-3);
    color: var(--ink);
    border-color: var(--hairline-bold);
  }
  .tier-chip.active {
    background: var(--ink);
    color: #0b0d11;
    border-color: var(--ink);
  }
  .tier-caption {
    margin-top: var(--s-3);
    color: var(--ink-faint);
    font-size: var(--t-sm);
  }

  .error {
    color: var(--danger);
    padding: var(--s-4);
    background: rgba(255, 59, 48, 0.08);
    border: 1px solid rgba(255, 59, 48, 0.2);
    border-radius: var(--r-lg);
  }

  @media (max-width: 720px) {
    /* Layout-specific: hero collapses to single column at 720 because
       the 220-320 art column gets cramped before the global mobile
       breakpoint (640). Section padding is token-driven and tightens
       at 640 via the global :root clamp. */
    .hero {
      grid-template-columns: 1fr;
      gap: var(--s-5);
    }
    .art-frame { max-width: 240px; }
  }
</style>
