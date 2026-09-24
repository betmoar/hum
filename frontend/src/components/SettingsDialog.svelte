<script lang="ts">
  import Settings from '../pages/Settings.svelte';
  import Icon from './Icon.svelte';

  type Props = {
    open: boolean;
    onclose: () => void;
  };
  let { open, onclose }: Props = $props();

  let dialog = $state<HTMLDialogElement | null>(null);

  // Same open/close-by-prop pattern as ConfirmDialog. The trigger (nav link,
  // or nothing for a deep link) is captured BEFORE showModal(), which moves
  // focus into the dialog, and gets focus back on close. showModal() also
  // restores focus natively in evergreen browsers; this doesn't rely on it.
  let previousFocus: Element | null = null;
  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) {
      previousFocus = document.activeElement;
      dialog.showModal();
    }
    if (!open && dialog.open) {
      dialog.close();
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
      previousFocus = null;
    }
  });
</script>

<dialog
  bind:this={dialog}
  class="settings-dialog"
  oncancel={(e) => { e.preventDefault(); onclose(); }}
  onclick={(e) => { if (e.target === dialog) onclose(); }}
  aria-labelledby="settings-dialog-title"
>
  <button class="close" onclick={onclose} aria-label="Close settings">
    <Icon name="x" size={20} />
  </button>
  <div class="dialog-body">
    <Settings />
  </div>
</dialog>

<style>
  .settings-dialog {
    position: relative;
    border: none;
    padding: 0;
    border-radius: var(--r-xl);
    background: var(--glass-4);
    color: var(--ink);
    width: min(640px, calc(100vw - var(--s-6) * 2));
    max-height: min(85vh, 760px);
    box-shadow: var(--inner-top-highlight), 0 40px 100px rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(40px) saturate(180%);
    -webkit-backdrop-filter: blur(40px) saturate(180%);
    animation: fade-in var(--dur-base) var(--ease);
  }
  .settings-dialog::backdrop {
    background: rgba(7, 9, 12, 0.35);
    backdrop-filter: blur(40px) saturate(180%);
    -webkit-backdrop-filter: blur(40px) saturate(180%);
  }
  .dialog-body {
    max-height: min(85vh, 760px);
    overflow-y: auto;
  }
  /* Settings.svelte's own <section> owns the content padding/max-width —
     the dialog shell only adds the close button and the scroll boundary. */
  .close {
    position: absolute;
    top: var(--s-4);
    right: var(--s-4);
    z-index: 1;
    width: 36px;
    height: 36px;
    padding: 0;
    border-radius: 50%;
    background: var(--glass-2);
    border: 1px solid var(--hairline-soft);
    display: grid;
    place-items: center;
    color: var(--ink);
    box-shadow: none;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
  .close:hover:not(:disabled) {
    background: var(--glass-3);
  }
</style>
