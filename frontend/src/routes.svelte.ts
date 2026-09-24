import type { Component } from 'svelte';
import Search from './pages/Search.svelte';
import Video from './pages/Video.svelte';
import Playlist from './pages/Playlist.svelte';
import Queue from './pages/Queue.svelte';
import Radio from './pages/Radio.svelte';

export type Match = {
  component: Component<any>;
  params: Record<string, string>;
};

function read(): string {
  return window.location.hash.slice(1) || '/';
}

// Settings is a dialog, not a page (issue #17) — it has no entry here.
// matchPath never returns a Settings component; the deep link is handled
// by Router itself (see #redirectSettingsDeepLink).
function matchPath(path: string): Match {
  if (path === '/' || path === '') return { component: Search, params: {} };
  if (path === '/queue') return { component: Queue, params: {} };
  if (path === '/radio') return { component: Radio, params: {} };
  const m = path.match(/^\/video\/(.+)$/);
  if (m) return { component: Video, params: { id: m[1] } };
  const p = path.match(/^\/playlist\/(.+)$/);
  if (p) return { component: Playlist, params: { id: p[1] } };
  return { component: Search, params: {} };
}

class Router {
  path = $state(read());
  match = $derived(matchPath(this.path));
  // Settings dialog visibility. Independent of `path` on purpose — opening
  // it must never unmount the current page (that's the whole point of #17).
  settingsOpen = $state(false);

  constructor() {
    this.#redirectSettingsDeepLink();
    window.addEventListener('hashchange', () => {
      this.path = read();
      this.#redirectSettingsDeepLink();
    });
  }

  // A stored/shared `#/settings` link must still open Settings. Replace the
  // hash with `/` (so `path` never settles on `/settings` and the SPA fallback
  // never has to route there) and open the dialog over whatever page that
  // leaves mounted.
  #redirectSettingsDeepLink(): void {
    if (this.path !== '/settings') return;
    this.settingsOpen = true;
    this.path = '/';
    window.location.hash = '/';
  }

  navigate(p: string): void {
    window.location.hash = p;
  }

  openSettings(): void {
    this.settingsOpen = true;
  }

  closeSettings(): void {
    this.settingsOpen = false;
  }
}

export const router = new Router();
