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

describe('Playlist page — duplicate video_id (review finding #1)', () => {
  it('renders both rows when a playlist contains the same video twice', async () => {
    vi.spyOn(api, 'playlist').mockResolvedValue({
      ...samplePlaylist,
      items: [
        { video_id: 'dup', title: 'Dup A', author: 'Artist A', duration_seconds: 100, thumbnail_url: '' },
        { video_id: 'dup', title: 'Dup B', author: 'Artist B', duration_seconds: 100, thumbnail_url: '' },
      ],
    });
    const { findByText, container } = render(Playlist, { props: { id: 'PL123' } });
    await findByText('Great Mix');
    expect(await findByText('Dup A')).toBeTruthy();
    expect(await findByText('Dup B')).toBeTruthy();
    expect(container.querySelectorAll('.item.compact')).toHaveLength(2);
  });
});

describe('Playlist page — Play all ordering + in-flight guard (review finding #2)', () => {
  const orderedPlaylist: PlaylistInfo = {
    playlist_id: 'PL123',
    title: 'Great Mix',
    author: 'Some Channel',
    video_count: 3,
    items: [
      { video_id: 'a', title: 'Track A2', author: 'Artist A', duration_seconds: 10, thumbnail_url: '' },
      { video_id: 'b', title: 'Track B2', author: 'Artist B', duration_seconds: 20, thumbnail_url: '' },
      { video_id: 'c', title: 'Track C2', author: 'Artist C', duration_seconds: 30, thumbnail_url: '' },
    ],
  };
  const opusA = {
    itag: 251, mime_type: 'audio/webm; codecs="opus"', bitrate: 160000, codec: 'opus',
    url: '/proxy/audio/a?itag=251',
  };

  it('plays track 1 now and inserts tracks 2..N ahead of the previously-queued tracks', async () => {
    vi.spyOn(api, 'playlist').mockResolvedValue(orderedPlaylist);
    const storeMod = await import('../../src/lib/store.svelte');
    storeMod.store.clear();
    storeMod.store.enqueueStubs([
      { videoId: 'x', title: 'X', author: '', durationSeconds: 1, thumbnailUrl: '' },
      { videoId: 'y', title: 'Y', author: '', durationSeconds: 1, thumbnailUrl: '' },
    ]);
    vi.spyOn(api, 'video').mockResolvedValue({
      video_id: 'a', title: 'Track A2', author: 'Artist A', duration_seconds: 10,
      thumbnail_url: '', audio_formats: [opusA], video_formats: [],
    } as any);

    const { findByText, getByText } = render(Playlist, { props: { id: 'PL123' } });
    await findByText('Great Mix');
    const btn = getByText(/play all/i);
    await fireEvent.click(btn);

    await waitFor(() => expect(storeMod.store.player.current?.videoId).toBe('a'));
    expect(storeMod.store.queue.map((t) => t.videoId)).toEqual(['b', 'c', 'x', 'y']);
  });

  it('a second click while Play all is in flight does not re-fetch the first track', async () => {
    vi.spyOn(api, 'playlist').mockResolvedValue(orderedPlaylist);
    const storeMod = await import('../../src/lib/store.svelte');
    storeMod.store.clear();
    let resolveVideo!: (v: Awaited<ReturnType<typeof api.video>>) => void;
    const videoSpy = vi.spyOn(api, 'video').mockImplementation(
      () => new Promise<Awaited<ReturnType<typeof api.video>>>((res) => { resolveVideo = res; }),
    );

    const { findByText, getByText } = render(Playlist, { props: { id: 'PL123' } });
    await findByText('Great Mix');
    const btn = getByText(/play all/i);
    await fireEvent.click(btn);
    await fireEvent.click(btn);

    expect(videoSpy).toHaveBeenCalledTimes(1);
    resolveVideo({
      video_id: 'a', title: 'Track A2', author: 'Artist A', duration_seconds: 10,
      thumbnail_url: '', audio_formats: [opusA], video_formats: [],
    } as any);
    await waitFor(() => expect(storeMod.store.player.current?.videoId).toBe('a'));
  });
});

describe('Playlist page — truncation + Load more (#19)', () => {
  const truncatedPlaylist: PlaylistInfo = {
    playlist_id: 'PLbig',
    title: 'Huge Mix',
    author: 'Some Channel',
    video_count: 500,
    truncated: true,
    items: [
      { video_id: 'aaa', title: 'Track A', author: 'Artist A', duration_seconds: 100, thumbnail_url: '' },
      { video_id: 'bbb', title: 'Track B', author: 'Artist B', duration_seconds: 200, thumbnail_url: '' },
    ],
  };

  it('shows "Showing N of M videos" and a Load more button when truncated', async () => {
    vi.spyOn(api, 'playlist').mockResolvedValue(truncatedPlaylist);
    const { findByText } = render(Playlist, { props: { id: 'PLbig' } });

    expect(await findByText('Showing 2 of 500 videos')).toBeTruthy();
    expect(await findByText('Load more (498 remaining)')).toBeTruthy();
    expect(await findByText('Play loaded')).toBeTruthy();
    expect(await findByText('Enqueue loaded')).toBeTruthy();
  });

  it('does not show Load more / "Showing N of M" when not truncated', async () => {
    vi.spyOn(api, 'playlist').mockResolvedValue(samplePlaylist);
    const { findByText, queryByText } = render(Playlist, { props: { id: 'PL123' } });
    await findByText('Great Mix');

    expect(queryByText(/load more/i)).toBeNull();
    expect(queryByText(/showing/i)).toBeNull();
    expect(await findByText('2 videos')).toBeTruthy();
  });

  it('Load more fetches the next window with start=items.length+1 and appends items', async () => {
    const playlistSpy = vi.spyOn(api, 'playlist').mockResolvedValueOnce(truncatedPlaylist);
    const { findByText, getByText, queryByText } = render(Playlist, { props: { id: 'PLbig' } });
    await findByText('Track B');

    playlistSpy.mockResolvedValueOnce({
      ...truncatedPlaylist,
      truncated: false,
      items: [
        { video_id: 'ccc', title: 'Track C', author: 'Artist C', duration_seconds: 300, thumbnail_url: '' },
      ],
    });

    const loadMoreBtn = getByText(/load more/i);
    await fireEvent.click(loadMoreBtn);

    expect(await findByText('Track C')).toBeTruthy();
    expect(playlistSpy).toHaveBeenCalledTimes(2);
    expect(playlistSpy).toHaveBeenLastCalledWith('PLbig', { start: 3 });
    // Items from the first page are still present; the response now reports
    // truncated: false, so the byline switches from "Showing N of M" to a
    // plain count and the Load more button disappears.
    expect(await findByText('Track A')).toBeTruthy();
    expect(await findByText('Track B')).toBeTruthy();
    expect(getByText('500 videos')).toBeTruthy();
    expect(queryByText(/load more/i)).toBeNull();
  });

  it('enqueueAll on a truncated playlist notifies with the "load more to add the rest" suffix', async () => {
    vi.spyOn(api, 'playlist').mockResolvedValue(truncatedPlaylist);
    const storeMod = await import('../../src/lib/store.svelte');
    storeMod.store.clear();
    const notifySpy = vi.spyOn(storeMod.store, 'notify').mockImplementation(() => {});

    const { findByText, getByText } = render(Playlist, { props: { id: 'PLbig' } });
    await findByText('Huge Mix');

    await fireEvent.click(getByText('Enqueue loaded'));

    await waitFor(() => expect(storeMod.store.queue).toHaveLength(2));
    expect(notifySpy).toHaveBeenCalledWith(
      'Added 2 tracks to queue of 500 (load more to add the rest).',
      'info',
    );
  });
});
