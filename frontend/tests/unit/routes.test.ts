import { describe, it, expect, beforeEach } from 'vitest';
import { router } from '../../src/routes.svelte';
import Search from '../../src/pages/Search.svelte';
import Video from '../../src/pages/Video.svelte';
import Playlist from '../../src/pages/Playlist.svelte';
import Queue from '../../src/pages/Queue.svelte';
import Radio from '../../src/pages/Radio.svelte';

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
  });

  it('a "/settings" deep link opens the dialog over "/" instead of routing there', () => {
    router.closeSettings();
    go('/settings');
    expect(router.path).toBe('/');
    expect(router.match.component).toBe(Search);
    expect(router.settingsOpen).toBe(true);
    router.closeSettings();
  });

  it('the deep-link redirect replaces the history entry instead of pushing one', () => {
    router.closeSettings();
    const len = history.length;
    go('/settings');
    expect(window.location.hash).toBe('#/');
    // go() itself pushes #/settings; the redirect must not add a second entry.
    expect(history.length).toBe(len + 1);
    router.closeSettings();
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

  it('captures the /playlist/:id param', () => {
    go('/playlist/PL1234567890');
    expect(router.match.component).toBe(Playlist);
    expect(router.match.params).toEqual({ id: 'PL1234567890' });
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
