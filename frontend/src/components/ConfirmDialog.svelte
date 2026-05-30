<script lang="ts">
  type Props = {
    open: boolean;
    title: string;
    message?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
    onconfirm: () => void;
    oncancel: () => void;
  };
  let { open, title, message = '', confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false, onconfirm, oncancel }: Props = $props();

  let dialog = $state<HTMLDialogElement | null>(null);

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  });
</script>

<dialog
  bind:this={dialog}
  oncancel={(e) => { e.preventDefault(); oncancel(); }}
  onclick={(e) => { if (e.target === dialog) oncancel(); }}
  aria-labelledby="confirm-dialog-title"
>
  <h3 id="confirm-dialog-title">{title}</h3>
  {#if message}<p>{message}</p>{/if}
  <div class="actions">
    <button onclick={oncancel}>{cancelLabel}</button>
    <button class="primary" class:danger onclick={onconfirm}>{confirmLabel}</button>
  </div>
</dialog>

<style>
  dialog {
    border: none;
    border-radius: var(--r-xl);
    padding: var(--s-5);
    background: var(--glass-4);
    color: var(--ink);
    max-width: 420px;
    box-shadow: var(--inner-top-highlight), 0 40px 100px rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(40px) saturate(180%);
    -webkit-backdrop-filter: blur(40px) saturate(180%);
    animation: fade-in var(--dur-base) var(--ease);
  }
  dialog::backdrop {
    background: rgba(7, 9, 12, 0.35);
    backdrop-filter: blur(40px) saturate(180%);
    -webkit-backdrop-filter: blur(40px) saturate(180%);
  }
  h3 {
    margin: 0 0 var(--s-3);
    font-family: var(--font-sans);
    font-size: var(--t-xl);
    font-weight: 500;
    letter-spacing: -0.01em;
  }
  p { margin: 0 0 var(--s-5); color: var(--ink-soft); }
  .actions {
    display: flex;
    gap: var(--s-3);
    justify-content: flex-end;
  }
  .primary {
    background: var(--accent);
    color: white;
    border-color: transparent;
  }
  .primary.danger {
    background: var(--danger);
    box-shadow: var(--inner-top-highlight);
  }
</style>
