import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import Search from '../../src/pages/Search.svelte';
import { api } from '../../src/lib/api';
import type { SearchResponse } from '../../src/lib/types';

// withRecent/loadRecent persist to this key (see src/lib/recentSearches.ts).
const KEY = 'hum.recent_searches';

const emptyResults: SearchResponse = { query: '', items: [] };

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('Search page recents banking', () => {
  it('debounced preview search does not bank the query into recents', async () => {
    const spy = vi.spyOn(api, 'search').mockResolvedValue(emptyResults);
    const { getByPlaceholderText } = render(Search);
    const input = getByPlaceholderText(/search/i) as HTMLInputElement;

    // Type a partial query; SearchBar fires oninput after its 350ms debounce.
    await fireEvent.input(input, { target: { value: 'lo-fi bea' } });
    await new Promise((r) => setTimeout(r, 400));

    expect(spy).toHaveBeenCalledWith('lo-fi bea', 30, expect.anything());
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it('explicit Enter submit banks the query into recents on success', async () => {
    vi.spyOn(api, 'search').mockResolvedValue(emptyResults);
    const { getByPlaceholderText } = render(Search);
    const input = getByPlaceholderText(/search/i) as HTMLInputElement;

    await fireEvent.input(input, { target: { value: 'brian eno' } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    // Submit's own fetch bypasses the debounce timer; let it resolve.
    await new Promise((r) => setTimeout(r, 0));

    expect(localStorage.getItem(KEY)).toBe(JSON.stringify(['brian eno']));
  });

  it('failed explicit submit does not bank the query', async () => {
    vi.spyOn(api, 'search').mockRejectedValue(new Error('boom'));
    const { getByPlaceholderText } = render(Search);
    const input = getByPlaceholderText(/search/i) as HTMLInputElement;

    await fireEvent.input(input, { target: { value: 'jazz' } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    await new Promise((r) => setTimeout(r, 0));

    expect(localStorage.getItem(KEY)).toBeNull();
  });
});
