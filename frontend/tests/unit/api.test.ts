import { describe, it, expect, beforeEach, vi } from 'vitest';
import { api, ApiError } from '../../src/lib/api';
import { store } from '../../src/lib/store.svelte';

beforeEach(() => {
  localStorage.clear();
  store.invalidateToken();
  store.clear();
  globalThis.fetch = vi.fn();
});

describe('api', () => {
  it('throws 401 without token', async () => {
    await expect(api.search('q')).rejects.toThrow(ApiError);
    await expect(api.search('q')).rejects.toMatchObject({ status: 401 });
  });

  it('injects bearer header', async () => {
    store.setToken('TOKEN');
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ query: 'q', items: [] }),
    });
    await api.search('q');
    const call = (globalThis.fetch as any).mock.calls[0];
    const init = call[1];
    expect(init.headers.Authorization).toBe('Bearer TOKEN');
  });

  it('returns parsed JSON on 200', async () => {
    store.setToken('T');
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ query: 'q', items: [{ id: 'a' }] }),
    });
    const r = await api.search('q');
    expect(r.items[0].id).toBe('a');
  });

  it('invalidates token on 401', async () => {
    store.setToken('T');
    (globalThis.fetch as any).mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => 'unauthorized',
    });
    await expect(api.search('q')).rejects.toThrow(ApiError);
    expect(store.settings.bearerToken).toBeNull();
  });

  it('throws ApiError on non-401 non-OK', async () => {
    store.setToken('T');
    (globalThis.fetch as any).mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => 'boom',
    });
    await expect(api.search('q')).rejects.toMatchObject({ status: 500 });
    expect(store.settings.bearerToken).toBe('T'); // not invalidated
  });

  it('builds search URL with limit', async () => {
    store.setToken('T');
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ query: 'q', items: [] }),
    });
    await api.search('hello world', 7);
    const url = (globalThis.fetch as any).mock.calls[0][0];
    expect(url).toBe('/api/search?q=hello%20world&limit=7');
  });

  it('builds video URL', async () => {
    store.setToken('T');
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    });
    await api.video('dQw4w9WgXcQ');
    expect((globalThis.fetch as any).mock.calls[0][0]).toBe('/api/video/dQw4w9WgXcQ');
  });
});

// The api module wraps each response in a title-normalisation pass. These
// tests exercise both the happy path (whitespace collapsed) and the
// defensive branches that early-return malformed payloads unchanged.
describe('api normalization wrappers', () => {
  beforeEach(() => store.setToken('T'));

  it('collapses double-spaces in search hits', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        query: 'q',
        items: [{ kind: 'video', id: 'a', title: 'Foo  (Bar)  (Baz)', thumbnail_url: '' }],
      }),
    });
    const r = await api.search('q');
    expect(r.items[0].title).toBe('Foo (Bar) (Baz)');
  });

  it('collapses whitespace in video detail title', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        video_id: 'a',
        title: 'Track  Name',
        author: 'X',
        channel_id: 'c',
        duration_seconds: 1,
        thumbnail_url: '',
        audio_formats: [],
        video_formats: [],
      }),
    });
    const r = await api.video('a');
    expect(r.title).toBe('Track Name');
  });

  it('normalises titles inside playlist items', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        playlist_id: 'p',
        title: 'List  Name',
        video_count: 1,
        items: [{ video_id: 'a', title: 'Inner   Title', thumbnail_url: '' }],
      }),
    });
    const r = await api.playlist('p');
    expect(r.title).toBe('List Name');
    expect(r.items[0].title).toBe('Inner Title');
  });

  it('returns search response unchanged when items array is absent', async () => {
    // Defensive branch: SearchResponse.items is required by the type, but
    // if the backend ever returns a malformed shape we must not crash.
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ query: 'q' }),
    });
    const r = await api.search('q');
    expect(r).toEqual({ query: 'q' });
  });

  it('returns video response unchanged when title is absent', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ video_id: 'a', author: 'X' }),
    });
    const r = await api.video('a');
    expect(r).toEqual({ video_id: 'a', author: 'X' });
  });

  it('returns channel response unchanged when title is absent', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ channel_id: 'c' }),
    });
    const r = await api.channel('c');
    expect(r).toEqual({ channel_id: 'c' });
  });

  it('returns playlist response unchanged when title and items are absent', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ playlist_id: 'p' }),
    });
    const r = await api.playlist('p');
    expect(r).toEqual({ playlist_id: 'p' });
  });
});

describe('api.search with options', () => {
  beforeEach(() => store.setToken('t'));

  it('forwards category=music as query param', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ query: '', items: [] }),
    });
    await api.search('foo', 10, { category: 'music' });
    const url = (globalThis.fetch as any).mock.calls[0][0];
    expect(url).toContain('category=music');
  });

  it('forwards live=true as query param', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ query: '', items: [] }),
    });
    await api.search('foo', 10, { live: true });
    const url = (globalThis.fetch as any).mock.calls[0][0];
    expect(url).toContain('live=true');
  });
});

describe('api.radio', () => {
  beforeEach(() => store.setToken('t'));

  it('calls GET /api/radio with limit', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ query: 'live music', items: [] }),
    });
    await api.radio({ limit: 30 });
    const url = (globalThis.fetch as any).mock.calls[0][0];
    expect(url).toContain('/api/radio');
    expect(url).toContain('limit=30');
  });
});
