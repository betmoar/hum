import { store } from './store.svelte';
import { normalizeTitle } from './format';
import type {
  ChannelInfo,
  PlaylistInfo,
  SearchResponse,
  VideoDetails,
} from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = store.settings.bearerToken;
  if (!token) throw new ApiError(401, 'no bearer token');

  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
    Authorization: `Bearer ${token}`,
  };

  const resp = await fetch(path, { ...init, headers });

  if (resp.status === 401) {
    store.invalidateToken();
    store.notify('Bearer token rejected. Paste a new one to continue.', 'error');
    throw new ApiError(401, 'invalid bearer');
  }
  if (!resp.ok) {
    const body = await resp.text().catch(() => '');
    throw new ApiError(resp.status, body || resp.statusText);
  }
  return (await resp.json()) as T;
}

// Normalise titles at the boundary so every consumer (pages, store, player)
// renders clean text without each having to remember the call. The wrappers
// below all delegate to `withTitle()` and `withItemTitles()` — when a 5th
// title-bearing response shape lands, add a one-line wrapper, not a copy
// of the normalisation logic.
function withTitle<T extends { title?: string | null }>(x: T): T {
  return x?.title ? { ...x, title: normalizeTitle(x.title) } : x;
}
function withItemTitles<T extends { items?: { title?: string | null }[] }>(x: T): T {
  if (!x?.items) return x;
  return { ...x, items: x.items.map(withTitle) as T['items'] };
}
function cleanSearch(r: SearchResponse): SearchResponse { return withItemTitles(r); }
function cleanVideo(d: VideoDetails): VideoDetails { return withTitle(d); }
function cleanChannel(c: ChannelInfo): ChannelInfo { return withTitle(c); }
function cleanPlaylist(p: PlaylistInfo): PlaylistInfo { return withTitle(withItemTitles(p)); }

export type SearchOpts = { category?: 'music'; live?: boolean };

function buildSearchUrl(q: string, limit: number, opts?: SearchOpts): string {
  let url = `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`;
  if (opts?.category) url += `&category=${encodeURIComponent(opts.category)}`;
  if (opts?.live) url += `&live=true`;
  return url;
}

export const api = {
  search: (q: string, limit: number = 20, opts?: SearchOpts): Promise<SearchResponse> =>
    request<SearchResponse>(buildSearchUrl(q, limit, opts)).then(cleanSearch),

  radio: (opts?: { limit?: number }): Promise<SearchResponse> => {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set('limit', String(opts.limit));
    const qs = params.toString();
    return request<SearchResponse>(`/api/radio${qs ? '?' + qs : ''}`).then(cleanSearch);
  },

  video: (id: string): Promise<VideoDetails> =>
    request<VideoDetails>(`/api/video/${id}`).then(cleanVideo),

  channel: (id: string): Promise<ChannelInfo> =>
    request<ChannelInfo>(`/api/channel/${id}`).then(cleanChannel),

  playlist: (id: string): Promise<PlaylistInfo> =>
    request<PlaylistInfo>(`/api/playlist/${id}`).then(cleanPlaylist),
};
