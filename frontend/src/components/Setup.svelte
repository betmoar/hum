<script lang="ts">
  import { store } from '../lib/store.svelte';
  import HumMark from './HumMark.svelte';

  let token = $state('');
  let error = $state<string | null>(null);

  function save() {
    if (token.length < 16) {
      error = 'Token must be at least 16 characters';
      return;
    }
    error = null;
    store.setToken(token.trim());
  }
</script>

<div class="stage">
  <div class="setup glass">
    <div class="mark">
      <HumMark size={44} />
    </div>
    <h2>Welcome to <em>Hum</em></h2>
    <p class="lede">Paste your bearer token to unlock the library.</p>

    <label for="token">Bearer token</label>
    <input
      id="token"
      type="password"
      placeholder="Bearer token"
      autocomplete="off"
      spellcheck="false"
      bind:value={token}
      onkeydown={(e) => e.key === 'Enter' && save()}
    />

    <button class="primary save" onclick={save}>Save & continue</button>

    {#if error}<p class="error">{error}</p>{/if}
  </div>
</div>

<style>
  .stage {
    min-height: 100vh;
    display: grid;
    place-items: center;
    padding: var(--s-5);
  }
  .setup {
    width: 100%;
    max-width: 460px;
    padding: var(--s-6) var(--s-6) var(--s-5);
    border-radius: var(--r-xl);
    display: flex;
    flex-direction: column;
    gap: var(--s-3);
    animation: fade-in var(--dur-slow) var(--ease);
  }
  /* Flat coral mark — no plate, no glow. The mark IS the identity. */
  .mark {
    display: grid;
    place-items: center;
    color: var(--accent);
    margin-bottom: var(--s-3);
  }
  h2 {
    font-size: var(--t-3xl);
    line-height: 1.05;
  }
  h2 em {
    font-style: italic;
    color: var(--accent);
  }
  .lede {
    color: var(--ink-soft);
    font-size: var(--t-base);
    margin-bottom: var(--s-3);
  }
  /* Sentence case per brand voice; weight 500 (never 600+). */
  label {
    font-size: var(--t-xs);
    letter-spacing: 0.01em;
    color: var(--ink-muted);
    font-weight: 500;
  }
  .save {
    margin-top: var(--s-3);
    width: 100%;
    padding: 14px;
    font-size: var(--t-base);
    border-radius: var(--r-md);
  }
  .error {
    color: var(--danger);
    font-size: var(--t-sm);
    margin-top: var(--s-2);
  }
</style>
