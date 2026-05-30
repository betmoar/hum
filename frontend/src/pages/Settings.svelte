<script lang="ts">
  import { store } from '../lib/store.svelte';
  import ConfirmDialog from '../components/ConfirmDialog.svelte';
  import { themeStore } from '../lib/theme.svelte';
  import { THEMES, type ThemeId } from '../themes/registry';

  function pickTheme(id: ThemeId) {
    themeStore.set(id);
  }

  let confirmTokenOpen = $state(false);
  let confirmQueueOpen = $state(false);

  function clearToken() { confirmTokenOpen = true; }
  function doCloseToken() { confirmTokenOpen = false; }
  function doConfirmToken() { store.invalidateToken(); confirmTokenOpen = false; }

  function clearQueue() { confirmQueueOpen = true; }
  function doCloseQueue() { confirmQueueOpen = false; }
  function doConfirmQueue() { store.clear(); confirmQueueOpen = false; }
</script>

<section>
  <header>
    <p class="eyebrow">Preferences</p>
    <h1>Settings</h1>
  </header>

  <div class="panel glass">
    <div class="row">
      <div class="row-meta">
        <h3>Authentication</h3>
        <p>Your bearer token is stored locally in this browser.</p>
      </div>
      <button onclick={clearToken}>Clear token</button>
    </div>

    <div class="divider"></div>

    <div class="row">
      <div class="row-meta">
        <h3>Queue</h3>
        <p>Remove every track from the playback queue.</p>
      </div>
      <button onclick={clearQueue}>Clear queue</button>
    </div>

    <div class="divider"></div>

    <div class="row">
      <div class="row-meta">
        <h3>Default quality</h3>
        <p>Used when starting a track from search results.</p>
      </div>
      <div class="seg" role="radiogroup" aria-label="Default quality">
        <label class="seg-opt">
          <input
            type="radio"
            name="defaultQuality"
            value="hi"
            checked={store.settings.defaultQuality === 'hi'}
            onchange={() => store.setDefaultQuality('hi')}
          />
          <span>Hi</span>
        </label>
        <label class="seg-opt">
          <input
            type="radio"
            name="defaultQuality"
            value="low"
            checked={store.settings.defaultQuality === 'low'}
            onchange={() => store.setDefaultQuality('low')}
          />
          <span>Low</span>
        </label>
      </div>
    </div>

    <div class="divider"></div>

    <div class="row">
      <div class="row-meta">
        <h3>Music only</h3>
        <p>Filter search results to the music category. Turn off to search everything on YouTube.</p>
      </div>
      <label class="toggle">
        <input
          type="checkbox"
          checked={store.settings.musicOnly}
          onchange={(e) => store.setMusicOnly((e.currentTarget as HTMLInputElement).checked)}
        />
        <span class="toggle-track" aria-hidden="true"></span>
      </label>
    </div>

    <div class="divider"></div>

    <div class="row">
      <div class="row-meta">
        <h3>Theme</h3>
        <p>Visual style for the app.</p>
      </div>
      <div class="theme-options" role="radiogroup" aria-label="Theme">
        {#each THEMES as t (t.id)}
          <label class="theme-option">
            <input
              type="radio"
              name="theme"
              value={t.id}
              checked={themeStore.current === t.id}
              onchange={() => pickTheme(t.id)}
            />
            <span class="theme-option-label">
              <span class="theme-option-name">{t.name}</span>
              <span class="theme-option-desc">{t.description}</span>
            </span>
          </label>
        {/each}
      </div>
    </div>

  </div>
  <footer class="about-footer">Hum v0.2 — sound, at home.</footer>
</section>

<style>
  section {
    padding: var(--container-pad-block-start) var(--container-pad-inline) var(--container-pad-block-end);
    max-width: var(--container-max-narrow);
    margin: 0 auto;
  }
  header { margin-bottom: var(--s-6); }
  h1 {
    font-family: var(--font-sans);
    font-size: clamp(28px, 5vw, 32px);
    font-weight: 500;
    letter-spacing: -0.02em;
    line-height: 1;
  }

  .panel {
    padding: var(--s-5) var(--s-6);
    border-radius: var(--r-xl);
  }
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s-4);
    padding: var(--s-4) 0;
  }
  .row-meta { min-width: 0; }
  .row h3 {
    font-family: var(--font-sans);
    font-size: var(--t-lg);
    font-weight: 500;
    margin-bottom: 4px;
    letter-spacing: -0.005em;
  }
  .row p {
    color: var(--ink-soft);
    font-size: var(--t-sm);
  }
  .theme-options {
    display: flex;
    flex-direction: column;
    gap: var(--s-2);
    min-width: 280px;
  }
  .theme-option {
    display: flex;
    align-items: flex-start;
    gap: var(--s-3);
    padding: var(--s-2) var(--s-3);
    border-radius: var(--r-md);
    cursor: pointer;
  }
  .theme-option:hover { background: var(--glass-1); }
  .theme-option input { margin-top: 4px; accent-color: var(--accent); }
  .theme-option-label {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .theme-option-name {
    font-size: var(--t-base);
    font-weight: 500;
    color: var(--ink);
  }
  .theme-option-desc {
    font-size: var(--t-sm);
    color: var(--ink-soft);
  }
  .seg {
    display: inline-flex;
    background: var(--glass-2);
    border: 1px solid var(--hairline-soft);
    border-radius: var(--r-pill);
    padding: 4px;
    gap: 2px;
  }
  .seg-opt {
    position: relative;
  }
  .seg-opt input {
    position: absolute; opacity: 0; pointer-events: none;
  }
  .seg-opt span {
    display: inline-block;
    padding: 6px 16px;
    border-radius: var(--r-pill);
    color: var(--ink-soft);
    font-size: var(--t-sm);
    cursor: pointer;
  }
  .seg-opt input:checked + span {
    background: var(--ink);
    color: #0b0d11;
  }
  .toggle {
    position: relative;
    display: inline-block;
    width: 44px; height: 24px;
  }
  .toggle input {
    position: absolute; opacity: 0; width: 0; height: 0;
  }
  .toggle-track {
    position: absolute; inset: 0;
    background: var(--glass-3);
    border: 1px solid var(--hairline);
    border-radius: 999px;
    transition: background var(--dur-fast) var(--ease);
    cursor: pointer;
  }
  .toggle-track::after {
    content: '';
    position: absolute;
    top: 2px; left: 2px;
    width: 18px; height: 18px;
    border-radius: 50%;
    background: var(--ink);
    transition: transform var(--dur-fast) var(--ease);
  }
  .toggle input:checked + .toggle-track { background: var(--accent); }
  .toggle input:checked + .toggle-track::after { transform: translateX(20px); background: white; }
  .divider {
    height: 1px;
    background: var(--hairline-soft);
  }

  .about-footer {
    margin-top: var(--s-5);
    color: var(--ink-faint);
    font-size: var(--t-xs);
    text-align: center;
  }

  @media (max-width: 560px) {
    /* Layout-specific: panels tighten and rows stack on very narrow
       viewports. Section padding tightens earlier at 640 via the
       global :root clamp. */
    .panel { padding: var(--s-4); }
    .row { flex-direction: column; align-items: stretch; }
    .row button { align-self: flex-start; }
    .theme-options { min-width: 0; }
  }
</style>

<ConfirmDialog
  open={confirmTokenOpen}
  title="Clear bearer token?"
  message="You will need to paste your token again to use the app."
  confirmLabel="Clear token"
  danger
  onconfirm={doConfirmToken}
  oncancel={doCloseToken}
/>

<ConfirmDialog
  open={confirmQueueOpen}
  title="Clear queue?"
  message="This removes every track from the playback queue."
  confirmLabel="Clear queue"
  danger
  onconfirm={doConfirmQueue}
  oncancel={doCloseQueue}
/>
