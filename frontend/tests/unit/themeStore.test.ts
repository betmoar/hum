import { describe, it, expect, beforeEach, vi } from 'vitest';

const KEY = 'hum.theme';

async function freshStore() {
  // The store is a module-level singleton constructed once on import. To
  // observe `readInitial()` under different DOM / localStorage states, reset
  // the module cache so each test re-runs construction.
  vi.resetModules();
  const mod = await import('../../src/lib/theme.svelte');
  return mod.themeStore;
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});

describe('ThemeStore', () => {
  it('defaults to glass when no DOM attribute and no stored value', async () => {
    const s = await freshStore();
    expect(s.current).toBe('glass');
  });

  it('reads initial state from the DOM data-theme attribute', async () => {
    document.documentElement.dataset.theme = 'analog';
    const s = await freshStore();
    expect(s.current).toBe('analog');
  });

  it('falls back to glass when DOM data-theme is an unknown value', async () => {
    document.documentElement.dataset.theme = 'fuchsia-dream';
    const s = await freshStore();
    expect(s.current).toBe('glass');
  });

  it('set() updates state, DOM, and localStorage', async () => {
    const s = await freshStore();
    s.set('analog');
    expect(s.current).toBe('analog');
    expect(document.documentElement.dataset.theme).toBe('analog');
    expect(localStorage.getItem(KEY)).toBe('analog');
  });

  it('set() rejects an unknown id silently', async () => {
    const s = await freshStore();
    // @ts-expect-error — intentionally passing invalid id
    s.set('fuchsia-dream');
    expect(s.current).toBe('glass');
    expect(document.documentElement.dataset.theme).not.toBe('fuchsia-dream');
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it('set() is idempotent for the current theme', async () => {
    const s = await freshStore();
    s.set('glass');
    expect(s.current).toBe('glass');
    expect(localStorage.getItem(KEY)).toBe('glass');
  });
});
