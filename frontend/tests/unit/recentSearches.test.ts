import { describe, it, expect, beforeEach, vi } from 'vitest';
import { loadRecent, withRecent, MAX_RECENT } from '../../src/lib/recentSearches';

const KEY = 'hum.recent_searches';

beforeEach(() => {
  localStorage.clear();
});

describe('loadRecent', () => {
  it('returns [] when the key is missing', () => {
    expect(loadRecent()).toEqual([]);
  });

  it('returns the persisted list when valid', () => {
    localStorage.setItem(KEY, JSON.stringify(['lo-fi', 'brian eno']));
    expect(loadRecent()).toEqual(['lo-fi', 'brian eno']);
  });

  it('returns [] when the payload is malformed JSON', () => {
    localStorage.setItem(KEY, 'not json {{{');
    expect(loadRecent()).toEqual([]);
  });

  it('returns [] when the payload is JSON but not an array', () => {
    localStorage.setItem(KEY, JSON.stringify({ recents: ['lo-fi'] }));
    expect(loadRecent()).toEqual([]);
  });

  it('filters non-string elements out of a mixed array', () => {
    localStorage.setItem(KEY, JSON.stringify(['lo-fi', 42, null, 'jazz', { q: 'x' }]));
    expect(loadRecent()).toEqual(['lo-fi', 'jazz']);
  });

  it('caps the result at MAX_RECENT even if storage has more', () => {
    const tooMany = Array.from({ length: MAX_RECENT + 5 }, (_, i) => `q${i}`);
    localStorage.setItem(KEY, JSON.stringify(tooMany));
    const result = loadRecent();
    expect(result).toHaveLength(MAX_RECENT);
    expect(result[0]).toBe('q0');
  });

  it('returns [] when getItem throws (e.g. storage disabled)', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage disabled');
    });
    try {
      expect(loadRecent()).toEqual([]);
    } finally {
      spy.mockRestore();
    }
  });
});

describe('withRecent', () => {
  it('prepends a new query to the front of the list', () => {
    const next = withRecent(['jazz'], 'lo-fi');
    expect(next).toEqual(['lo-fi', 'jazz']);
  });

  it('returns a copy of the input when query is empty', () => {
    const input = ['jazz'];
    const next = withRecent(input, '');
    expect(next).toEqual(['jazz']);
    expect(next).not.toBe(input); // never aliases caller's array
  });

  it('returns a copy of the input when query is whitespace-only', () => {
    expect(withRecent(['jazz'], '   \t  ')).toEqual(['jazz']);
  });

  it('trims surrounding whitespace before storing', () => {
    expect(withRecent([], '  lo-fi  ')).toEqual(['lo-fi']);
  });

  it('dedupes case-insensitively, moving existing entry to the top', () => {
    const next = withRecent(['jazz', 'Lo-Fi', 'classical'], 'LO-FI');
    expect(next).toEqual(['LO-FI', 'jazz', 'classical']);
  });

  it('caps the list at MAX_RECENT, dropping the oldest', () => {
    const full = Array.from({ length: MAX_RECENT }, (_, i) => `q${i}`);
    const next = withRecent(full, 'newest');
    expect(next).toHaveLength(MAX_RECENT);
    expect(next[0]).toBe('newest');
    expect(next).not.toContain(`q${MAX_RECENT - 1}`);
  });

  it('persists the new list to localStorage as JSON', () => {
    withRecent(['jazz'], 'lo-fi');
    expect(localStorage.getItem(KEY)).toBe(JSON.stringify(['lo-fi', 'jazz']));
  });

  it('round-trips through loadRecent', () => {
    const next = withRecent([], 'lo-fi');
    withRecent(next, 'jazz');
    expect(loadRecent()).toEqual(['jazz', 'lo-fi']);
  });

  it('swallows localStorage write errors silently', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    try {
      expect(() => withRecent([], 'lo-fi')).not.toThrow();
      // In-memory list still reflects the push even if persistence failed.
      expect(withRecent([], 'lo-fi')).toEqual(['lo-fi']);
    } finally {
      spy.mockRestore();
    }
  });
});
