import type { AudioFormat, Quality } from './types';
import { detectAudioEnv, type AudioEnv } from './browserEnv';

function preferredFamily(env: AudioEnv): 'aac' | 'opus' {
  // Safari (hlsNative) wants the AAC+HLS path. Everyone else prefers opus.
  return env.hlsNative ? 'aac' : 'opus';
}

function sameFamily(formats: AudioFormat[], family: 'aac' | 'opus'): AudioFormat[] {
  return formats.filter((f) => f.codec === family);
}

export function pickForTier(
  formats: AudioFormat[],
  tier: Quality,
  env: AudioEnv,
): AudioFormat | null {
  if (formats.length === 0) return null;

  const family = preferredFamily(env);
  const inFamily = sameFamily(formats, family);

  if (inFamily.length === 0) {
    // No preferred-family format available. Try the opposite family.
    const other = sameFamily(formats, family === 'aac' ? 'opus' : 'aac');
    if (other.length > 0) {
      const sorted = [...other].sort((a, b) => b.bitrate - a.bitrate);
      return tier === 'hi' ? sorted[0] : sorted[sorted.length - 1];
    }
    return formats[0];
  }

  // Safari Hi prefers AAC with hls_url specifically; fall through to AAC if none exist.
  if (family === 'aac' && tier === 'hi') {
    const withHls = inFamily.filter((f) => f.hls_url);
    const pool = withHls.length > 0 ? withHls : inFamily;
    return [...pool].sort((a, b) => b.bitrate - a.bitrate)[0];
  }

  const sorted = [...inFamily].sort((a, b) => b.bitrate - a.bitrate);
  return tier === 'hi' ? sorted[0] : sorted[sorted.length - 1];
}

// Legacy wrapper preserved so callers we haven't migrated keep working.
// New code MUST use pickForTier directly.
export function pickAudio(formats: AudioFormat[]): AudioFormat | null {
  return pickForTier(formats, 'hi', detectAudioEnv());
}
