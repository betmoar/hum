import type { Component } from 'svelte';
import Search from './pages/Search.svelte';
import Video from './pages/Video.svelte';
import Queue from './pages/Queue.svelte';
import Radio from './pages/Radio.svelte';
import Settings from './pages/Settings.svelte';

export type Match = {
  component: Component<any>;
  params: Record<string, string>;
};

function read(): string {
  return window.location.hash.slice(1) || '/';
}

function matchPath(path: string): Match {
  if (path === '/' || path === '') return { component: Search, params: {} };
  if (path === '/queue') return { component: Queue, params: {} };
  if (path === '/radio') return { component: Radio, params: {} };
  if (path === '/settings') return { component: Settings, params: {} };
  const m = path.match(/^\/video\/(.+)$/);
  if (m) return { component: Video, params: { id: m[1] } };
  return { component: Search, params: {} };
}

class Router {
  path = $state(read());
  match = $derived(matchPath(this.path));

  constructor() {
    window.addEventListener('hashchange', () => {
      this.path = read();
    });
  }

  navigate(p: string): void {
    window.location.hash = p;
  }
}

export const router = new Router();
