import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import Playlist from '../../src/pages/Playlist.svelte';
import { api, ApiError } from '../../src/lib/api';
import type { PlaylistInfo } from '../../src/lib/types';

const samplePlaylist: PlaylistInfo = {
  playlist_id: 'PL123',
  title: 'Great Mix',
  author: 'Some Channel',
  video_count: 2,
  items: [
    { video_id: 'aaa', title: 'Track A', author: 'Artist A', duration_seconds: 100, thumbnail_url: '' },
    { video_id: 'bbb', title: 'Track B', author: 'Artist B', duration_seconds: 200, thumbnail_url: '' },
  ],
};

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('Playlist page', () => {
  it('renders items from a mocked api.playlist', async () => {
    vi.spyOn(api, 'playlist').mockResolvedValue(samplePlaylist);
    const { findByText } = render(Playlist, { props: { id: 'PL123' } });

    expect(await findByText('Great Mix')).toBeTruthy();
    expect(await findByText('Track A')).toBeTruthy();
    expect(await findByText('Track B')).toBeTruthy();
  });

  it('"Enqueue all" enqueues all ids in order', async () => {
    vi.spyOn(api, 'playlist').mockResolvedValue(samplePlaylist);
    const storeMod = await import('../../src/lib/store.svelte');
    storeMod.store.clear();
    const videoSpy = vi.spyOn(api, 'video');
    const notifySpy = vi.spyOn(storeMod.store, 'notify').mockImplementation(() => {});

    const { findByText, getByText } = render(Playlist, { props: { id: 'PL123' } });
    await findByText('Great Mix');

    const btn = getByText(/enqueue all/i);
    await fireEvent.click(btn);

    await waitFor(() => expect(storeMod.store.queue).toHaveLength(2));
    expect(storeMod.store.queue.map((t) => t.videoId)).toEqual(['aaa', 'bbb']);
    expect(storeMod.store.queue[0]).toMatchObject({ title: 'Track A', durationSeconds: 100, audioUrl: '' });
    // No per-track /api/video round-trip: URLs are fetched when a track plays.
    expect(videoSpy).not.toHaveBeenCalled();
    expect(notifySpy).toHaveBeenCalledTimes(1);
  });

  it('renders error state on rejection', async () => {
    vi.spyOn(api, 'playlist').mockRejectedValue(new ApiError(404, 'VIDEO_UNAVAILABLE'));
    const { findByText } = render(Playlist, { props: { id: 'RDxyz' } });

    expect(await findByText(/VIDEO_UNAVAILABLE/i)).toBeTruthy();
  });
});

describe('Playlist page — hero', () => {
  it('shows the first track thumbnail as cover and compact rows', async () => {
    vi.spyOn(api, 'playlist').mockResolvedValue({
      ...samplePlaylist,
      items: samplePlaylist.items.map((i, n) => ({ ...i, thumbnail_url: `https://i.ytimg.com/vi/${n}/hq.jpg` })),
    });
    const { findByText, container } = render(Playlist, { props: { id: 'PL123' } });
    await findByText('Great Mix');
    expect(container.querySelector('.art-frame img')?.getAttribute('src')).toBe('https://i.ytimg.com/vi/0/hq.jpg');
    expect(container.querySelectorAll('.item.compact')).toHaveLength(2);
  });
});
