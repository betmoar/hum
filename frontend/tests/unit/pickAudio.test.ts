import { describe, it, expect } from 'vitest';
import { pickForTier, pickAudio } from '../../src/lib/pickAudio';
import type { AudioFormat } from '../../src/lib/types';

const opusHi: AudioFormat = { itag: 251, mime_type: 'audio/webm; codecs="opus"', bitrate: 160000, codec: 'opus', url: '/proxy/audio/x?itag=251' };
const opusLow: AudioFormat = { itag: 249, mime_type: 'audio/webm; codecs="opus"', bitrate: 50000, codec: 'opus', url: '/proxy/audio/x?itag=249' };
const aacHi: AudioFormat = { itag: 140, mime_type: 'audio/mp4; codecs="mp4a.40.2"', bitrate: 128000, codec: 'aac', url: '/proxy/audio/x?itag=140', hls_url: '/api/hls/x?itag=140' };
const aacLow: AudioFormat = { itag: 139, mime_type: 'audio/mp4; codecs="mp4a.40.2"', bitrate: 48000, codec: 'aac', url: '/proxy/audio/x?itag=139', hls_url: '/api/hls/x?itag=139' };

const chromeEnv = { hlsNative: false, supportsOpus: true, supportsAac: true };
const safariEnv = { hlsNative: true, supportsOpus: false, supportsAac: true };
const braveEnv = { hlsNative: false, supportsOpus: true, supportsAac: true };

describe('pickForTier', () => {
  it('Chrome Hi -> highest opus', () => {
    expect(pickForTier([opusLow, opusHi, aacHi, aacLow], 'hi', chromeEnv)).toBe(opusHi);
  });
  it('Chrome Low -> lowest opus (same family)', () => {
    expect(pickForTier([opusLow, opusHi, aacHi, aacLow], 'low', chromeEnv)).toBe(opusLow);
  });
  it('Safari Hi -> highest AAC with hls_url', () => {
    expect(pickForTier([opusHi, opusLow, aacHi, aacLow], 'hi', safariEnv)).toBe(aacHi);
  });
  it('Safari Low -> lowest AAC (same family)', () => {
    expect(pickForTier([opusHi, opusLow, aacHi, aacLow], 'low', safariEnv)).toBe(aacLow);
  });
  it('Brave behaves like Chrome', () => {
    expect(pickForTier([opusLow, opusHi, aacHi, aacLow], 'hi', braveEnv)).toBe(opusHi);
  });
  it('falls back to formats[0] when no codec family matches', () => {
    const odd: AudioFormat = { itag: 999, mime_type: 'audio/wav', bitrate: 64000, codec: 'wav', url: '/x' };
    expect(pickForTier([odd], 'hi', chromeEnv)).toBe(odd);
  });
  it('Hi == Low when only one bitrate exists in the chosen family', () => {
    expect(pickForTier([opusHi], 'low', chromeEnv)).toBe(opusHi);
  });
  it('returns null on empty input', () => {
    expect(pickForTier([], 'hi', chromeEnv)).toBeNull();
  });
});

describe('pickAudio (legacy wrapper)', () => {
  it('delegates to pickForTier with tier=hi', () => {
    expect(pickAudio([opusLow, opusHi])).toBe(opusHi);
  });
});
