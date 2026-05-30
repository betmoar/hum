import { DEFAULT_THEME, THEME_IDS, type ThemeId } from '../themes/registry';

const KEY_THEME = 'hum.theme';

function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && (THEME_IDS as readonly string[]).includes(value);
}

function readInitial(): ThemeId {
  // The inline bootstrap in index.html sets <html data-theme> before any
  // module loads. In tests (and as a defensive fallback), accept that as the
  // initial state when valid, otherwise fall back to the default.
  if (typeof document !== 'undefined') {
    const fromDom = document.documentElement.dataset.theme;
    if (isThemeId(fromDom)) return fromDom;
  }
  return DEFAULT_THEME;
}

class ThemeStore {
  /**
   * Current theme id. Use `set()` to change it — direct assignment bypasses
   * DOM and localStorage sync and will desync the page.
   */
  current = $state<ThemeId>(readInitial());

  set(id: ThemeId): void {
    if (!isThemeId(id)) return;
    this.current = id;
    if (typeof document !== 'undefined') {
      document.documentElement.dataset.theme = id;
    }
    try {
      localStorage.setItem(KEY_THEME, id);
    } catch {
      // try/catch covers both ReferenceError (e.g. non-browser env where
      // localStorage is undefined) and QuotaExceededError / SecurityError
      // (private browsing, storage disabled). Best-effort persistence.
    }
  }
}

export const themeStore = new ThemeStore();
