<script lang="ts">
  import { store } from '../lib/store.svelte';
  import { formatDuration } from '../lib/format';
  import QueueItem from '../components/QueueItem.svelte';
  import ConfirmDialog from '../components/ConfirmDialog.svelte';

  function remove(idx: number) {
    store.remove(idx);
  }

  function reorderQueue(from: number, to: number) { store.reorder(from, to); }

  let confirmClearOpen = $state(false);
  function clear() { confirmClearOpen = true; }
  function doClear() { store.clear(); confirmClearOpen = false; }
</script>

<section>
  <header>
    <div>
      <p class="eyebrow">Up next</p>
      <h1>Queue</h1>
    </div>
    {#if store.queue.length > 0}
      <button class="destructive" onclick={clear}>Clear all</button>
    {/if}
  </header>

  {#if store.player.current}
    <div class="now-playing glass">
      <p class="eyebrow">Now playing</p>
      <div class="now-body">
        {#if store.player.current.thumbnailUrl}
          <img class="art" src={store.player.current.thumbnailUrl} alt="" />
        {/if}
        <div class="now-text">
          <div class="now-title">{store.player.current.title}</div>
          <div class="now-author">{store.player.current.author} · {formatDuration(store.player.current.durationSeconds)}</div>
        </div>
      </div>
    </div>
  {/if}

  <div class="queue-list" role="list">
    {#each store.queue as track, i (track.videoId + ':' + i)}
      <QueueItem
        {track}
        index={i}
        onremove={remove}
        onreorder={reorderQueue}
      />
    {:else}
      <p class="empty">Nothing queued. Search for something to play.</p>
    {/each}
  </div>
</section>

<ConfirmDialog
  open={confirmClearOpen}
  title="Clear queue?"
  message="This removes every track from the playback queue."
  confirmLabel="Clear queue"
  danger
  onconfirm={doClear}
  oncancel={() => confirmClearOpen = false}
/>

<style>
  section {
    padding: var(--container-pad-block-start) var(--container-pad-inline) var(--container-pad-block-end);
    max-width: var(--container-max);
    margin: 0 auto;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: var(--s-4);
    margin-bottom: var(--s-6);
  }
  h1 {
    font-family: var(--font-sans);
    font-size: clamp(28px, 5vw, 32px);
    font-weight: 500;
    letter-spacing: -0.02em;
    line-height: 1;
  }

  /* Now-playing card — full emphasis, distinct from queued rows */
  .now-playing {
    background: var(--glass-4);
    border: 1px solid var(--hairline-bold);
    border-radius: var(--r-xl);
    padding: var(--s-5);
    display: flex;
    flex-direction: column;
    gap: var(--s-3);
    margin-bottom: var(--s-5);
  }
  .now-playing .eyebrow {
    margin-bottom: 0;
  }
  .now-body {
    display: flex;
    gap: var(--s-4);
    align-items: center;
  }
  .art {
    width: 80px;
    height: 80px;
    border-radius: var(--r-md);
    object-fit: cover;
    flex-shrink: 0;
    border: 1px solid var(--hairline-soft);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
  }
  .now-text { min-width: 0; }
  .now-title {
    font-family: var(--font-sans);
    font-size: var(--t-xl);
    line-height: 1.1;
    letter-spacing: -0.01em;
    margin-bottom: 4px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .now-author {
    color: var(--ink-soft);
    font-size: var(--t-base);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Queued rows sit visually inset relative to the now-playing card */
  .queue-list {
    display: flex;
    flex-direction: column;
    gap: var(--s-2);
    padding: 0 var(--s-4);
  }

  .empty {
    color: var(--ink-faint);
    padding: var(--s-7) 0;
    text-align: center;
    font-style: italic;
    font-family: var(--font-sans);
    font-size: var(--t-lg);
  }

  @media (max-width: 640px) {
    /* Section padding handled by the global --container-* mobile clamp.
       Layout-specific adjustments remain here. */
    .art { width: 64px; height: 64px; }
    .now-title { font-size: var(--t-lg); }
    .queue-list { padding: 0 var(--s-2); }
  }
</style>
