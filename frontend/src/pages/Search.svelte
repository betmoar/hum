<script lang="ts">
  import SearchBar from '../components/SearchBar.svelte';
  import ResultList from '../components/ResultList.svelte';
  import Spinner from '../components/Spinner.svelte';
  import { api } from '../lib/api';
  import { loadRecent, withRecent } from '../lib/recentSearches';
  import { store } from '../lib/store.svelte';
  import type { SearchHit } from '../lib/types';

  let loading = $state(false);
  let error = $state<string | null>(null);
  let items = $state<SearchHit[]>([]);
  let query = $state('');
  let recents = $state<string[]>(loadRecent());

  async function onsubmit(q: string) {
    query = q;
    loading = true;
    error = null;
    items = [];
    try {
      const opts = store.settings.musicOnly ? { category: 'music' as const } : undefined;
      const r = await api.search(q, 30, opts);
      items = r.items;
      // Only persist on successful submit (no point banking failed queries).
      recents = withRecent(recents, q);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Search failed';
    } finally {
      loading = false;
    }
  }

  async function ondebounced(q: string) {
    await onsubmit(q);
  }
</script>

<section>
  <header class="hero">
    <h1>Discover</h1>
    <p class="kicker">Search anything on YouTube — stream the audio, queue the night.</p>
  </header>

  <SearchBar {onsubmit} oninput={ondebounced} />

  {#if loading}
    <Spinner />
  {:else if error}
    <p class="error">{error}</p>
  {:else if query}
    <p class="meta">Results for <em>"{query}"</em></p>
    <ResultList {items} />
  {:else}
    <div class="placeholder">
      {#if recents.length > 0}
        <p class="eyebrow">Recent searches</p>
        <div class="recent-chips">
          {#each recents as q (q)}
            <button type="button" class="chip" onclick={() => onsubmit(q)}>{q}</button>
          {/each}
        </div>
      {/if}
      <p class="hint">Try a song, an artist, a genre, a mood.</p>
    </div>
  {/if}
</section>

<style>
  section {
    padding: var(--container-pad-block-start) var(--container-pad-inline) var(--container-pad-block-end);
    max-width: var(--container-max);
    margin: 0 auto;
  }
  .hero {
    margin-bottom: var(--s-6);
  }
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
  .meta {
    color: var(--ink-muted);
    margin: var(--s-6) 0 var(--s-3);
    font-size: var(--t-sm);
  }
  .meta em {
    color: var(--ink);
    font-style: italic;
    font-family: var(--font-sans);
    font-size: var(--t-lg);
  }
  .placeholder {
    margin-top: var(--s-6);
  }
  /* The hint sits centred and editorial regardless of whether recents are
     present — it's the "what kind of room is this" line. When recents are
     present it follows them; on a fresh install it floats alone over the
     living-glass wash. */
  .placeholder .hint {
    color: var(--ink-faint);
    font-style: italic;
    font-family: var(--font-sans);
    font-size: var(--t-xl);
    text-align: center;
    margin-top: var(--s-6);
  }
  /* Recent-search chip cloud — content-aware density for return users.
     Left-aligned under the eyebrow so it reads as a list, not a hero. */
  .recent-chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s-2);
  }
  .chip {
    font-size: var(--t-sm);
    padding: 8px 14px;
    border-radius: var(--r-pill);
    background: var(--glass-1);
    border: 1px solid var(--hairline-soft);
    color: var(--ink-soft);
    box-shadow: var(--inner-top-highlight);
    backdrop-filter: blur(20px) saturate(170%);
    -webkit-backdrop-filter: blur(20px) saturate(170%);
    letter-spacing: -0.005em;
  }
  .chip:hover:not(:disabled) {
    background: var(--glass-3);
    color: var(--ink);
    border-color: var(--hairline);
  }
  .error {
    color: var(--danger);
    padding: var(--s-4);
    margin-top: var(--s-5);
    background: rgba(255, 59, 48, 0.08);
    border: 1px solid rgba(255, 59, 48, 0.2);
    border-radius: var(--r-lg);
  }

  /* No page-local @media — section padding is token-driven via the
     global --container-* mobile clamp in app.css. */
</style>
