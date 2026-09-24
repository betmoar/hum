import { describe, it, expect, beforeEach } from 'vitest';
import { getBookmark, saveBookmark, clearBookmark, BOOKMARK_MAX_ENTRIES } from '../../src/lib/bookmarks';

beforeEach(() => localStorage.clear());

describe('bookmarks', () => {
  it('ignores short tracks', () => {
    saveBookmark('a', 100, 599);
    expect(getBookmark('a')).toBeNull();
  });

  it('saves long tracks', () => {
    saveBookmark('a', 100, 600);
    expect(getBookmark('a')).toBe(100);
  });

  it('clears near the end', () => {
    saveBookmark('a', 100, 1000);
    saveBookmark('a', 971, 1000);
    expect(getBookmark('a')).toBeNull();
  });

  it('does not keep a position under 5 s', () => {
    saveBookmark('a', 3, 1000);
    expect(getBookmark('a')).toBeNull();
  });

  it('clearBookmark removes', () => {
    saveBookmark('a', 100, 1000);
    clearBookmark('a');
    expect(getBookmark('a')).toBeNull();
  });

  it('evicts oldest beyond cap', () => {
    for (let i = 0; i <= BOOKMARK_MAX_ENTRIES; i++) saveBookmark('v' + i, 100, 1000, i);
    expect(getBookmark('v0')).toBeNull();
    expect(getBookmark('v1')).toBe(100);
    expect(getBookmark('v' + BOOKMARK_MAX_ENTRIES)).toBe(100);
  });

  it('survives corrupt storage', () => {
    localStorage.setItem('hum.bookmarks', '{bad');
    expect(getBookmark('a')).toBeNull();
    saveBookmark('a', 100, 1000);
    expect(getBookmark('a')).toBe(100);
  });

  it('ignores non-object storage', () => {
    localStorage.setItem('hum.bookmarks', '[1,2]');
    expect(getBookmark('0')).toBeNull();
  });
});
