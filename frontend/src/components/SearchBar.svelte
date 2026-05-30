<script lang="ts">
  import Icon from './Icon.svelte';

  type Props = {
    onsubmit: (q: string) => void;
    oninput?: (q: string) => void;
    debounceMs?: number;
  };
  let { onsubmit, oninput, debounceMs = 350 }: Props = $props();

  let value = $state('');
  let timer: ReturnType<typeof setTimeout> | null = null;

  function submit() {
    if (timer) { clearTimeout(timer); timer = null; }
    const q = value.trim();
    if (!q) return;
    onsubmit(q);
  }

  function handleInput() {
    if (!oninput) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      const q = value.trim();
      if (q.length >= 2) oninput(q);
    }, debounceMs);
  }
</script>

<div class="wrap">
  <span class="icon"><Icon name="search" size={20} /></span>
  <input
    type="search"
    placeholder="Search YouTube..."
    bind:value
    oninput={handleInput}
    onkeydown={(e) => e.key === 'Enter' && submit()}
  />
</div>

<style>
  .wrap {
    position: relative;
    width: 100%;
  }
  .icon {
    position: absolute;
    left: 20px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--ink-muted);
    pointer-events: none;
    display: flex;
    align-items: center;
  }
  input[type="search"] {
    width: 100%;
    padding: 16px 22px 16px 52px;
    font-size: var(--t-lg);
    font-family: var(--font-sans);
    border-radius: var(--r-pill);
  }
  /* Suppress the WebKit cancel button — looks foreign on the
     frosted pill input. */
  input[type="search"]::-webkit-search-cancel-button {
    -webkit-appearance: none;
    appearance: none;
  }
</style>
