<script lang="ts">
  import type { SearchHit } from '../lib/types';
  import { formatDuration } from '../lib/format';
  import { router } from '../routes.svelte';
  import { store } from '../lib/store.svelte';
  import Icon from './Icon.svelte';

  type Props = { hit: SearchHit };
  let { hit }: Props = $props();

  let imgFailed = $state(false);

  function open() {
    if (hit.kind === 'video') router.navigate(`/video/${hit.id}`);
  }
  function playNow(e: MouseEvent) {
    e.stopPropagation();
    void store.playNowById(hit.id);
  }
  function enqueue(e: MouseEvent) {
    e.stopPropagation();
    void store.enqueueById(hit.id);
  }
</script>

<div
  class="item"
  role="button"
  tabindex="0"
  aria-disabled={hit.kind !== 'video' ? 'true' : 'false'}
  onclick={open}
  onkeydown={(e) => { if (hit.kind === 'video' && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); open(); } }}
>
  <div class="thumb">
    {#if hit.thumbnail_url && !imgFailed}
      <img src={hit.thumbnail_url} alt="" loading="lazy" onerror={() => imgFailed = true} />
    {:else}
      <div class="img-placeholder"></div>
    {/if}
    {#if hit.is_live}
      <span class="live-badge" aria-label="Live now">LIVE</span>
    {:else if hit.kind === 'video' && hit.duration_seconds}
      <span class="dur-badge">{formatDuration(hit.duration_seconds)}</span>
    {/if}
  </div>
  <div class="meta">
    <div class="title">{hit.title}</div>
    {#if hit.author}<div class="author">{hit.author}</div>{/if}
    <div class="kind">{hit.kind}</div>
  </div>
  {#if hit.kind === 'video'}
    <div class="actions">
      <button class="action" aria-label="Play now" onclick={playNow}>
        <Icon name="play" size={18} />
      </button>
      <button class="action" aria-label="Add to queue" onclick={enqueue}>
        <Icon name="list-plus" size={18} />
      </button>
    </div>
  {/if}
</div>

<style>
  .item {
    display: flex;
    gap: var(--s-4);
    width: 100%;
    text-align: left;
    padding: var(--s-3);
    background: var(--glass-1);
    border: 1px solid var(--hairline-soft);
    border-radius: var(--r-lg);
    box-shadow: var(--inner-top-highlight);
    align-items: center;
    transition:
      background var(--dur-fast) var(--ease),
      border-color var(--dur-fast) var(--ease),
      transform var(--dur-fast) var(--ease);
    backdrop-filter: blur(30px) saturate(170%);
    -webkit-backdrop-filter: blur(30px) saturate(170%);
    cursor: pointer;
  }
  .item[aria-disabled="true"] {
    opacity: 0.45;
    cursor: default;
  }
  .item:hover:not([aria-disabled="true"]) {
    background: var(--glass-2);
    border-color: var(--hairline);
    transform: translateY(-1px);
  }

  .thumb {
    position: relative;
    width: 140px;
    aspect-ratio: 16 / 9;
    border-radius: var(--r-sm);
    overflow: hidden;
    flex-shrink: 0;
    background: var(--glass-2);
  }
  .thumb img, .img-placeholder {
    width: 100%; height: 100%; object-fit: cover; display: block;
  }
  .img-placeholder { background: linear-gradient(135deg, var(--glass-3), var(--glass-1)); }
  .dur-badge {
    position: absolute; bottom: 6px; right: 6px;
    padding: 2px 8px; border-radius: var(--r-pill);
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    font-size: var(--t-xs); color: white;
    font-variant-numeric: tabular-nums;
  }
  .live-badge {
    position: absolute; top: 6px; left: 6px;
    padding: 2px 8px; border-radius: var(--r-pill);
    background: var(--danger, #ff3b30);
    font-size: var(--t-xs); font-weight: 600;
    color: white; letter-spacing: 0.04em;
  }

  .meta {
    flex: 1; min-width: 0;
    display: flex; flex-direction: column; gap: 2px;
  }
  .title {
    font-family: var(--font-sans);
    font-size: var(--t-lg);
    line-height: 1.2;
    letter-spacing: -0.01em;
    color: var(--ink);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .author { color: var(--ink-soft); font-size: var(--t-sm); }
  .kind {
    color: var(--ink-faint);
    font-size: var(--t-sm);
    letter-spacing: 0.01em;
    margin-top: 2px;
  }

  .actions {
    display: flex; gap: var(--s-2);
    flex-shrink: 0;
  }
  .action {
    width: 36px; height: 36px;
    display: grid; place-items: center;
    border-radius: 50%;
    background: var(--glass-2);
    border: 1px solid var(--hairline-soft);
    color: var(--ink);
  }
  .action:hover { background: var(--glass-3); border-color: var(--hairline); }

  @media (max-width: 560px) {
    .thumb { width: 110px; }
    .title { font-size: var(--t-base); }
    .actions { flex-direction: column; }
  }
</style>
