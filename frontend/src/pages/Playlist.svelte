<script lang="ts">
  import { api, ApiError } from '../lib/api';
  import { store } from '../lib/store.svelte';
  import Spinner from '../components/Spinner.svelte';
  import Icon from '../components/Icon.svelte';
  import ResultItem from '../components/ResultItem.svelte';
  import type { PlaylistInfo, PlaylistItem, SearchHit } from '../lib/types';

  type Props = { id: string };
  let { id }: Props = $props();

  let loading = $state(true);
  let error = $state<string | null>(null);
  let playlist = $state<PlaylistInfo | null>(null);

  $effect(() => {
    let cancelled = false;
    loading = true;
    error = null;
    api
      .playlist(id)
      .then((p) => { if (!cancelled) playlist = p; })
      .catch((e) => {
        if (cancelled) return;
        error = e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Load failed';
      })
      .finally(() => { if (!cancelled) loading = false; });
    return () => { cancelled = true; };
  });

  // Playlist listings carry no cover of their own; the first track's
  // thumbnail is what YouTube shows as the playlist cover too.
  const cover = $derived(playlist?.items.find((i) => i.thumbnail_url)?.thumbnail_url ?? '');

  function asHit(item: PlaylistItem): SearchHit {
    return {
      kind: 'video',
      id: item.video_id,
      title: item.title,
      author: item.author,
      thumbnail_url: item.thumbnail_url,
      duration_seconds: item.duration_seconds,
    };
  }

  // Tracks are queued from the playlist listing itself: one /api/video
  // round-trip (~2 s each) per track would make a 200-item list take minutes.
  // The Player fetches the signed URL when each track starts.
  function stub(item: PlaylistItem) {
    return {
      videoId: item.video_id,
      title: item.title,
      author: item.author ?? '',
      durationSeconds: item.duration_seconds ?? 0,
      thumbnailUrl: item.thumbnail_url,
    };
  }

  let playAllInFlight = $state(false);

  async function playAll() {
    if (!playlist || playlist.items.length === 0) return;
    if (playAllInFlight) return;
    playAllInFlight = true;
    try {
      const [first, ...rest] = playlist.items;
      await store.playNowById(first.video_id);
      // Only queue the rest if the first track actually became current —
      // playNowById is silent on failure (notifies internally), so re-check.
      if (store.player.current?.videoId === first.video_id) {
        store.enqueueStubs(rest.map(stub), { next: true });
      }
    } finally {
      playAllInFlight = false;
    }
  }

  function enqueueAll() {
    if (!playlist || playlist.items.length === 0) return;
    store.enqueueStubs(playlist.items.map(stub));
    store.notify(`Added ${playlist.items.length} tracks to queue.`, 'info');
  }
</script>

<section>
  {#if loading}
    <Spinner />
  {:else if error}
    <p class="error">{error}</p>
  {:else if playlist}
    <header class="hero">
      {#if cover}
        <div class="art-frame"><img src={cover} alt="" /></div>
      {/if}
      <div class="info">
        <p class="eyebrow">Playlist</p>
        <h1>{playlist.title}</h1>
        <p class="byline">
          {#if playlist.author}<span class="author">{playlist.author}</span><span class="dot">&middot;</span>{/if}
          <span>{playlist.video_count} video{playlist.video_count === 1 ? '' : 's'}</span>
        </p>
        <div class="actions">
          <button class="primary" onclick={playAll} disabled={playlist.items.length === 0 || playAllInFlight}>
            <Icon name="play" size={18} />
            Play all
          </button>
          <button onclick={enqueueAll} disabled={playlist.items.length === 0}>
            <Icon name="list-plus" size={18} />
            Enqueue all
          </button>
        </div>
      </div>
    </header>

    <div class="list">
      {#each playlist.items as item, i (`${i}:${item.video_id}`)}
        <ResultItem hit={asHit(item)} compact />
      {:else}
        <p class="empty">No videos in this playlist.</p>
      {/each}
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
    display: grid;
    grid-template-columns: minmax(180px, 260px) 1fr;
    gap: var(--s-6);
    align-items: end;
    margin-bottom: var(--s-7);
  }
  .hero:not(:has(.art-frame)) { grid-template-columns: 1fr; }
  .art-frame {
    aspect-ratio: 16 / 9;
    width: 100%;
    border-radius: var(--r-xl);
    overflow: hidden;
    border: 1px solid var(--hairline);
    box-shadow: var(--inner-top-highlight), 0 30px 60px rgba(0, 0, 0, 0.55);
    background: var(--glass-2);
  }
  .art-frame img { width: 100%; height: 100%; object-fit: cover; display: block; }
  @media (max-width: 720px) {
    .hero { grid-template-columns: 1fr; gap: var(--s-5); }
    .art-frame { max-width: 320px; }
  }
  .eyebrow {
    color: var(--ink-faint);
    font-size: var(--t-sm);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-bottom: var(--s-2);
  }
  h1 {
    font-family: var(--font-sans);
    font-size: clamp(28px, 4vw, 44px);
    line-height: 1.1;
    margin-bottom: var(--s-3);
  }
  .byline {
    color: var(--ink-soft);
    font-size: var(--t-lg);
    margin-bottom: var(--s-5);
    display: flex;
    flex-wrap: wrap;
    gap: var(--s-2);
    align-items: center;
  }
  .byline .author { color: var(--ink); font-weight: 500; }
  .byline .dot { color: var(--ink-faint); }

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

  .error {
    color: var(--danger);
    padding: var(--s-4);
    background: rgba(255, 59, 48, 0.08);
    border: 1px solid rgba(255, 59, 48, 0.2);
    border-radius: var(--r-lg);
  }
</style>
