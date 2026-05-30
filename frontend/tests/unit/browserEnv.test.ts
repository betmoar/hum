import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('detectAudioEnv', () => {
  beforeEach(() => {
    // Re-import after each test by clearing the vite cache so the memo resets.
    vi.resetModules();
  });

  it('returns hlsNative=true when audio reports HLS support', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockImplementation(
      (mime: string) => (mime === 'application/vnd.apple.mpegurl' ? 'probably' : '')
    );
    const { detectAudioEnv } = await import('../../src/lib/browserEnv');
    const env = detectAudioEnv();
    expect(env.hlsNative).toBe(true);
  });

  it('returns hlsNative=false on Chromium-like environments', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('');
    const { detectAudioEnv } = await import('../../src/lib/browserEnv');
    const env = detectAudioEnv();
    expect(env.hlsNative).toBe(false);
  });

  it('reports supportsOpus and supportsAac independently', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockImplementation(
      (mime: string) => {
        if (mime.includes('opus')) return 'probably';
        if (mime.includes('mp4a')) return 'maybe';
        return '';
      }
    );
    const { detectAudioEnv } = await import('../../src/lib/browserEnv');
    const env = detectAudioEnv();
    expect(env.supportsOpus).toBe(true);
    expect(env.supportsAac).toBe(true);
  });

  it('memoises across calls', async () => {
    const { detectAudioEnv, _resetAudioEnvForTests } = await import('../../src/lib/browserEnv');
    _resetAudioEnvForTests();
    const spy = vi
      .spyOn(HTMLMediaElement.prototype, 'canPlayType')
      .mockReturnValue('probably');
    detectAudioEnv();
    const callsAfterFirst = spy.mock.calls.length;
    detectAudioEnv();
    expect(spy.mock.calls.length).toBe(callsAfterFirst);
  });
});
