<script lang="ts">
  import { store } from '../lib/store.svelte';
  import Icon from './Icon.svelte';
</script>

{#if store.toast}
  {@const toast = store.toast}
  <div class="toast" class:error={toast.kind === 'error'} role="status" aria-live="polite">
    <span class="msg">{toast.message}</span>
    {#if toast.action}
      <button onclick={toast.action.onclick}>{toast.action.label}</button>
    {/if}
    <button class="close" onclick={() => store.dismissToast()} aria-label="Dismiss">
      <Icon name="x" size={16} />
    </button>
  </div>
{/if}

<style>
  .toast {
    position: fixed;
    left: 50%;
    transform: translateX(-50%);
    bottom: calc(var(--player-h, 96px) + var(--s-4));
    z-index: 50;
    display: inline-flex;
    align-items: center;
    gap: var(--s-3);
    padding: var(--s-3) var(--s-4);
    max-width: 90vw;
    background: var(--glass-4);
    border: 1px solid var(--hairline);
    border-radius: var(--r-pill);
    box-shadow: var(--inner-top-highlight), 0 20px 50px rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(40px) saturate(180%);
    -webkit-backdrop-filter: blur(40px) saturate(180%);
    animation: fade-in var(--dur-base) var(--ease);
    font-size: var(--t-sm);
  }
  .toast.error { border-color: rgba(255, 107, 107, 0.4); color: var(--danger); }
  .msg { color: var(--ink); }
  .toast.error .msg { color: var(--danger); }
  .close {
    width: 28px;
    height: 28px;
    padding: 0;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: transparent;
    border: none;
    color: var(--ink-muted);
  }
  .close:hover { color: var(--ink); background: var(--glass-2); }
</style>
