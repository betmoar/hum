<script lang="ts">
  import ResultList from '../components/ResultList.svelte';
  import Spinner from '../components/Spinner.svelte';
  import { api } from '../lib/api';
  import type { SearchHit } from '../lib/types';

  let loading = $state(true);
  let error = $state<string | null>(null);
  let items = $state<SearchHit[]>([]);

  // Pre-warm hls.js: kick off the dynamic import as soon as the user lands on
  // /radio so the chunk is fetched, parsed, and ready by the time they click
  // Play. Cuts cold-start latency from ~2.5s (import + parse + manifest +
  // first segment) down to ~700ms (manifest + first segment only). Cached
  // by the browser after first /radio visit; subsequent visits are instant.
  $effect(() => {
    void import('hls.js').catch(() => { /* network-offline is fine, will retry on Play */ });
  });

  $effect(() => {
    let cancelled = false;
    loading = true;
    error = null;
    api
      .radio({ limit: 30 })
      .then((r) => { if (!cancelled) items = r.items; })
      .catch((e) => {
        if (!cancelled) error = e instanceof Error ? e.message : 'Load failed';
      })
      .finally(() => { if (!cancelled) loading = false; });
    return () => { cancelled = true; };
  });
</script>

<section>
  <header class="hero">
    <h1>Radio</h1>
    <p class="kicker">Live music, right now.</p>
  </header>

  {#if loading}
    <Spinner />
  {:else if error}
    <p class="error">{error}</p>
  {:else if items.length === 0}
    <p class="empty">Nothing live right now. Try again later.</p>
  {:else}
    <ResultList {items} />
  {/if}
</section>

<style>
  section {
    padding: var(--container-pad-block-start) var(--container-pad-inline) var(--container-pad-block-end);
    max-width: var(--container-max);
    margin: 0 auto;
  }
  .hero { margin-bottom: var(--s-6); }
  h1 {
    font-family: var(--font-sans);
    font-size: clamp(28px, 5vw, 32px);
    font-weight: 500;
    letter-spacing: -0.02em;
    line-height: 1;
    margin-bottom: var(--s-3);
  }
  .kicker {
    color: var(--ink-soft);
    font-size: var(--t-lg);
    max-width: 540px;
  }
  .empty {
    color: var(--ink-faint);
    font-style: italic;
    font-family: var(--font-sans);
    font-size: var(--t-xl);
    text-align: center;
    margin-top: var(--s-6);
  }
  .error {
    color: var(--danger);
    padding: var(--s-4);
    margin-top: var(--s-5);
    background: rgba(255, 59, 48, 0.08);
    border: 1px solid rgba(255, 59, 48, 0.2);
    border-radius: var(--r-lg);
  }
</style>
