<script lang="ts">
  import type { Track } from '../lib/types';
  import { formatDuration } from '../lib/format';
  import Icon from './Icon.svelte';

  type Props = {
    track: Track;
    index: number;
    onremove: (idx: number) => void;
    onreorder: (from: number, to: number) => void;
  };
  let { track, index, onremove, onreorder }: Props = $props();

  // Drop-target indicator for the row being dragged OVER (not the dragged row).
  // Uses a depth counter so child dragenter/leave doesn't flicker it off.
  let dropDepth = $state(0);
  let isDropTarget = $derived(dropDepth > 0);
  let isDragging = $state(false);

  // Track failed image loads so we swap to a deliberate placeholder rather
  // than showing the browser's broken-image grey square.
  let imgFailed = $state(false);

  function reset() {
    dropDepth = 0;
    isDragging = false;
  }
</script>

<div
  class="row"
  class:drop-target={isDropTarget}
  class:dragging={isDragging}
  role="listitem"
  draggable="true"
  ondragstart={(e) => {
    e.dataTransfer?.setData('text/plain', String(index));
    isDragging = true;
  }}
  ondragend={reset}
  ondragenter={() => { dropDepth += 1; }}
  ondragleave={() => { dropDepth = Math.max(0, dropDepth - 1); }}
  ondragover={(e) => { e.preventDefault(); }}
  ondrop={(e) => {
    e.preventDefault();
    reset();
    const fromStr = e.dataTransfer?.getData('text/plain');
    if (fromStr == null) return;
    const from = Number(fromStr);
    if (Number.isFinite(from) && from !== index) onreorder(from, index);
  }}
>
  {#if track.thumbnailUrl && !imgFailed}
    <img class="thumb" src={track.thumbnailUrl} alt="" loading="lazy" onerror={() => imgFailed = true} />
  {:else}
    <div class="thumb thumb-placeholder"></div>
  {/if}
  <div class="meta">
    <div class="title">{track.title}</div>
    <div class="author">{track.author} · {formatDuration(track.durationSeconds)}</div>
  </div>
  <span class="grip" aria-hidden="true">
    <Icon name="grip-vertical" size={18} />
  </span>
  <button class="remove" onclick={() => onremove(index)} aria-label="Remove from queue">
    <Icon name="x" size={18} />
  </button>
</div>

<style>
  .row {
    display: flex;
    align-items: center;
    gap: var(--s-4);
    padding: var(--s-3) var(--s-4);
    background: var(--glass-1);
    border: 1px solid var(--hairline-soft);
    border-radius: var(--r-lg);
    box-shadow: var(--inner-top-highlight);
    transition:
      background var(--dur-fast) var(--ease),
      transform var(--dur-fast) var(--ease);
    backdrop-filter: blur(30px) saturate(170%);
    -webkit-backdrop-filter: blur(30px) saturate(170%);
  }
  @media (hover: hover) {
    .row { cursor: grab; }
    .row:active { cursor: grabbing; }
  }
  .row:hover {
    background: var(--glass-2);
    transform: translateY(-1px);
  }
  .row.drop-target {
    border-color: var(--accent);
    background: var(--glass-3);
  }
  .row.dragging {
    opacity: 0.55;
  }
  .thumb {
    width: 48px;
    height: 48px;
    object-fit: cover;
    border-radius: var(--r-sm);
    flex-shrink: 0;
    border: 1px solid var(--hairline-soft);
  }
  .thumb-placeholder {
    /* Subtle shimmer so a missing-or-still-loading thumbnail reads as
       "loading" rather than "broken". Static fallback under reduced-motion. */
    background:
      linear-gradient(
        105deg,
        var(--glass-1) 0%,
        var(--glass-3) 40%,
        var(--glass-1) 80%
      );
    background-size: 220% 100%;
    background-position: 100% 0;
  }
  @media (prefers-reduced-motion: no-preference) {
    .thumb-placeholder {
      animation: thumb-shimmer 2.4s linear infinite;
    }
  }
  @keyframes thumb-shimmer {
    from { background-position: 200% 0; }
    to   { background-position: -100% 0; }
  }
  .meta { flex: 1; min-width: 0; }
  .title {
    font-weight: 500;
    font-size: var(--t-base);
    color: var(--ink);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .author {
    color: var(--ink-muted);
    font-size: var(--t-sm);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .grip {
    width: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    color: var(--ink-faint);
    cursor: grab;
  }
  .row:hover .grip {
    color: var(--ink-muted);
  }
  /* Drag-to-reorder is a pointer-hover affordance. On touch-only devices
     the icon is misleading (touch can't grab a handle in this app),
     so hide it. Reorder on touch is acceptable via remove + re-add. */
  @media (hover: none) and (pointer: coarse) {
    .grip { display: none; }
  }
  .remove {
    width: 36px;
    height: 36px;
    padding: 0;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: transparent;
    border: 1px solid transparent;
    color: var(--ink-muted);
    box-shadow: none;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    flex-shrink: 0;
  }
  .remove:hover:not(:disabled) {
    background: var(--glass-3);
    border-color: var(--hairline);
    color: var(--ink);
  }
</style>
