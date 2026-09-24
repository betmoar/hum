import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ResultItem from '../../src/components/ResultItem.svelte';
import { router } from '../../src/routes.svelte';

const videoHit = {
  kind: 'video' as const,
  id: 'abc',
  title: 'Test',
  author: 'A',
  thumbnail_url: '',
  duration_seconds: 100,
  is_live: false,
};

beforeEach(() => {
  localStorage.clear();
});

describe('ResultItem', () => {
  it('Play now button invokes store.playNowById and stops propagation', async () => {
    const storeMod = await import('../../src/lib/store.svelte');
    const spy = vi.spyOn(storeMod.store, 'playNowById').mockResolvedValue();
    const { getByLabelText } = render(ResultItem, { props: { hit: videoHit } });
    const btn = getByLabelText(/play now/i);
    await fireEvent.click(btn);
    expect(spy).toHaveBeenCalledWith('abc');
  });

  it('+Queue button invokes store.enqueueById', async () => {
    const storeMod = await import('../../src/lib/store.svelte');
    const spy = vi.spyOn(storeMod.store, 'enqueueById').mockResolvedValue();
    const { getByLabelText } = render(ResultItem, { props: { hit: videoHit } });
    const btn = getByLabelText(/add to queue/i);
    await fireEvent.click(btn);
    expect(spy).toHaveBeenCalledWith('abc');
  });

  it('hides action buttons for non-video kinds', () => {
    const channelHit = { ...videoHit, kind: 'channel' as const };
    const { queryByLabelText } = render(ResultItem, { props: { hit: channelHit } });
    expect(queryByLabelText(/play now/i)).toBeNull();
    expect(queryByLabelText(/add to queue/i)).toBeNull();
  });

  it('navigates to /playlist/:id on click for playlist hits', async () => {
    const navSpy = vi.spyOn(router, 'navigate');
    const playlistHit = { ...videoHit, kind: 'playlist' as const, id: 'PL1', video_count: 42 };
    const { getByRole } = render(ResultItem, { props: { hit: playlistHit } });
    const item = getByRole('button');
    expect(item.getAttribute('aria-disabled')).toBe('false');
    await fireEvent.click(item);
    expect(navSpy).toHaveBeenCalledWith('/playlist/PL1');
  });

  it('does not navigate for channel hits and marks them aria-disabled', async () => {
    const navSpy = vi.spyOn(router, 'navigate');
    navSpy.mockClear();
    const channelHit = { ...videoHit, kind: 'channel' as const, id: 'UC1' };
    const { getByRole } = render(ResultItem, { props: { hit: channelHit } });
    const item = getByRole('button');
    expect(item.getAttribute('aria-disabled')).toBe('true');
    await fireEvent.click(item);
    expect(navSpy).not.toHaveBeenCalled();
  });

  it('shows video_count in the meta line for playlist hits', () => {
    const playlistHit = { ...videoHit, kind: 'playlist' as const, id: 'PL1', video_count: 183 };
    const { getByText } = render(ResultItem, { props: { hit: playlistHit } });
    expect(getByText(/playlist.*183 videos/i)).toBeTruthy();
  });

  it('shows LIVE badge when is_live=true', () => {
    const liveHit = { ...videoHit, is_live: true };
    const { getByLabelText } = render(ResultItem, { props: { hit: liveHit } });
    expect(getByLabelText('Live now')).toBeTruthy();
  });
});

describe('ResultItem — live tracks', () => {
  it('keeps Play/Queue actions enabled for live tracks (hls.js everywhere)', async () => {
    // Used to be browser-gated when only Safari supported native HLS. Now
    // that hls.js handles live playback in all browsers, no gating.
    const envMod = await import('../../src/lib/browserEnv');
    envMod._resetAudioEnvForTests();
    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('');

    const liveHit = { ...videoHit, is_live: true };
    const { getByLabelText, queryByText } = render(ResultItem, { props: { hit: liveHit } });
    const playBtn = getByLabelText(/play now/i) as HTMLButtonElement;
    const queueBtn = getByLabelText(/add to queue/i) as HTMLButtonElement;
    expect(playBtn.disabled).toBe(false);
    expect(queueBtn.disabled).toBe(false);
    expect(queryByText(/Live playback requires Safari/i)).toBeNull();
  });
});

describe('ResultItem — compact + current', () => {
  it('compact hides the kind line', () => {
    const { container } = render(ResultItem, { props: { hit: videoHit, compact: true } });
    expect(container.querySelector('.kind')).toBeNull();
  });

  it('marks the currently playing video', async () => {
    const { store } = await import('../../src/lib/store.svelte');
    store.player.current = { videoId: videoHit.id, title: 't', author: 'a', durationSeconds: 1, thumbnailUrl: '', audioUrl: '', itag: 140 };
    const { container } = render(ResultItem, { props: { hit: videoHit } });
    expect(container.querySelector('.item')?.getAttribute('aria-current')).toBe('true');
    store.player.current = null;
  });
});
