<script lang="ts">
  import type { SearchHit } from '../lib/types';
  import ResultItem from './ResultItem.svelte';

  type Props = { items: SearchHit[] };
  let { items }: Props = $props();
</script>

<div class="list">
  {#each items as hit (hit.kind + ':' + hit.id)}
    <ResultItem {hit} />
  {:else}
    <p class="empty">No results.</p>
  {/each}
</div>

<style>
  .list {
    display: flex;
    flex-direction: column;
    gap: var(--s-2);
  }
  .empty {
    color: var(--ink-muted);
    padding: var(--s-5);
    text-align: center;
    font-style: italic;
    font-family: var(--font-sans);
    font-size: var(--t-lg);
  }
</style>
