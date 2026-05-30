import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ResultItem from '../../src/components/ResultItem.svelte';

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
