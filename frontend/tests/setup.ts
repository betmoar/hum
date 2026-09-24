import '@testing-library/jest-dom/vitest';
import { beforeEach } from 'vitest';

// jsdom does not implement ResizeObserver. Stub it so components that use it
// (e.g. Marquee.svelte) don't throw in the test environment.
if (typeof ResizeObserver === 'undefined') {
  (globalThis as any).ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom's <dialog> is a bare HTMLElement subclass — showModal()/close() exist
// as no-ops that don't flip `.open` or fire `close`/`cancel`. Every dialog in
// this app (ConfirmDialog, SettingsDialog) drives its open state off the
// `open` prop via `dialog.open`, so without this stub any test that renders
// one with open=true throws "showModal is not a function". Mirrors real
// HTMLDialogElement semantics just enough for tests: toggling `.open` and
// reflecting the `open` attribute.
if (typeof HTMLDialogElement !== 'undefined') {
  if (!HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
      this.setAttribute('open', '');
    };
  }
  if (!HTMLDialogElement.prototype.close) {
    HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
      this.removeAttribute('open');
      this.dispatchEvent(new Event('close'));
    };
  }
}

beforeEach(() => {
  localStorage.clear();
  // Reset fetch mock if set by tests.
  if ('fetch' in globalThis && (globalThis.fetch as any).mockReset) {
    (globalThis.fetch as any).mockReset();
  }
});
