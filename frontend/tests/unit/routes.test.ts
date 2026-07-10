import { describe, it, expect, beforeEach } from 'vitest';
import { router } from '../../src/routes.svelte';
import Search from '../../src/pages/Search.svelte';
import Video from '../../src/pages/Video.svelte';
import Queue from '../../src/pages/Queue.svelte';
import Radio from '../../src/pages/Radio.svelte';
import Settings from '../../src/pages/Settings.svelte';

// Drive the real router singleton: set location.hash and fire the hashchange
// event it listens for, then assert the derived match. This exercises the
// /video/:id capture and the unknown-path fallback end-to-end.

function go(path: string): void {
  window.location.hash = path;
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

beforeEach(() => {
  // Reset to home between tests.
  go('/');
});

describe('router matchPath', () => {
  it('routes "/" to Search', () => {
    go('/');
    expect(router.match.component).toBe(Search);
    expect(router.match.params).toEqual({});
  });

  it('routes the static pages', () => {
    go('/queue');
    expect(router.match.component).toBe(Queue);
    go('/radio');
    expect(router.match.component).toBe(Radio);
    go('/settings');
    expect(router.match.component).toBe(Settings);
  });

  it('captures the /video/:id param', () => {
    go('/video/dQw4w9WgXcQ');
    expect(router.match.component).toBe(Video);
    expect(router.match.params).toEqual({ id: 'dQw4w9WgXcQ' });
  });

  it('preserves an 11-char video id with no trailing slash', () => {
    go('/video/abcdefghijk');
    expect(router.match.params.id).toBe('abcdefghijk');
  });

  it('falls back to Search for an unknown path', () => {
    go('/nope/not-a-route');
    expect(router.match.component).toBe(Search);
    expect(router.match.params).toEqual({});
  });

  it('empty hash treats as home', () => {
    window.location.hash = '';
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(router.match.component).toBe(Search);
  });
});
