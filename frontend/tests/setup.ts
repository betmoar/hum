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

beforeEach(() => {
  localStorage.clear();
  // Reset fetch mock if set by tests.
  if ('fetch' in globalThis && (globalThis.fetch as any).mockReset) {
    (globalThis.fetch as any).mockReset();
  }
});
