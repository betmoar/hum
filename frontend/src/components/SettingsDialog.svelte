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
      // showModal() focuses the close button, which draws its focus ring on
      // open. Focus the dialog itself; Tab still enters the controls.
      dialog.focus();
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
  tabindex="-1"
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
  .settings-dialog:focus { outline: none; }
  /* Only .dialog-body scrolls; the <dialog> itself must not (Safari shows
     its own scrollbar on the UA default overflow: auto). */
  .settings-dialog { overflow: hidden; }
  .dialog-body {
    max-height: min(85vh, 760px);
    overflow-y: auto;
    overscroll-behavior: contain;
    /* No visible scrollbar (Safari ignores scrollbar-width: thin and draws
       a full-height bar); wheel, trackpad and touch still scroll, and the
       edge fade shows there is more below. */
    scrollbar-width: none;
    /* The scroll area starts below the close button, so scrolled content
       never slides under it, and stops short of the rounded corners. */
    --dialog-top: calc(var(--s-4) + 36px - var(--s-2));
    margin-top: var(--dialog-top);
    margin-bottom: var(--s-4);
    max-height: calc(min(85vh, 760px) - var(--dialog-top) - var(--s-4));
    mask-image: linear-gradient(to bottom, transparent 0, #000 var(--s-4), #000 calc(100% - var(--s-4)), transparent 100%);
  }
  .dialog-body::-webkit-scrollbar { display: none; }
  .dialog-body :global(header) { margin-bottom: var(--s-5); }
  /* Inside the dialog the page's own glass card would be a second frosted
     frame in a frosted frame: flatten it so the dialog is the only surface. */
  .dialog-body :global(section) {
    padding: var(--s-4) var(--s-6) var(--s-5);
  }
  .dialog-body :global(.panel) {
    background: none;
    border: none;
    box-shadow: none;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    padding: 0;
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
