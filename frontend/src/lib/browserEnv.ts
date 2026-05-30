export type AudioEnv = {
  hlsNative: boolean;
  supportsOpus: boolean;
  supportsAac: boolean;
};

let cached: AudioEnv | null = null;

function probe(mime: string): boolean {
  if (typeof document === 'undefined') return false;
  return document.createElement('audio').canPlayType(mime) !== '';
}

export function detectAudioEnv(): AudioEnv {
  if (cached) return cached;
  cached = {
    hlsNative: probe('application/vnd.apple.mpegurl'),
    supportsOpus: probe('audio/webm; codecs="opus"'),
    supportsAac: probe('audio/mp4; codecs="mp4a.40.2"'),
  };
  return cached;
}

// Test-only: reset the memo. Production code should never call this.
export function _resetAudioEnvForTests(): void {
  cached = null;
}
