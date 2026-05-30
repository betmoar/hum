// Sample the dominant hue from a thumbnail URL and write it to a CSS var.
// Uses a 1×1 canvas downsample for speed (no Color Thief dep).

let currentRequest = 0;

export function applyArtHue(url: string | null): void {
  const reqId = ++currentRequest;
  if (!url) {
    document.documentElement.style.removeProperty('--art-hue');
    return;
  }
  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.onload = () => {
    if (reqId !== currentRequest) return; // a newer request already started
    try {
      const c = document.createElement('canvas');
      c.width = 1;
      c.height = 1;
      const ctx = c.getContext('2d');
      if (!ctx) return;
      // Downsample to 1×1 — the average pixel is "good enough" for chromatic tinting.
      // Apple Music does something more elaborate (per-region sampling) but a single
      // pixel produces convincing results when used at 5-8% mix.
      ctx.drawImage(img, 0, 0, 1, 1);
      const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
      const hue = rgbToHue(r, g, b);
      if (hue == null) {
        // Greyscale artwork — let the chrome stay neutral rather than picking
        // an arbitrary fallback hue.
        document.documentElement.style.removeProperty('--art-hue');
      } else {
        document.documentElement.style.setProperty('--art-hue', String(hue));
      }
    } catch {
      // Cross-origin failure or canvas-tainted — fall back silently.
    }
  };
  img.onerror = () => {
    if (reqId === currentRequest) {
      document.documentElement.style.removeProperty('--art-hue');
    }
  };
  img.src = url;
}

/** Return the HSL hue (0-360) of the given RGB, or null if the colour is
 *  greyscale (no meaningful hue). */
export function rgbToHue(r: number, g: number, b: number): number | null {
  const rN = r / 255;
  const gN = g / 255;
  const bN = b / 255;
  const max = Math.max(rN, gN, bN);
  const min = Math.min(rN, gN, bN);
  const d = max - min;
  if (d === 0) return null;
  let h: number;
  if (max === rN) {
    h = ((gN - bN) / d) % 6;
  } else if (max === gN) {
    h = (bN - rN) / d + 2;
  } else {
    h = (rN - gN) / d + 4;
  }
  h = Math.round(h * 60);
  if (h < 0) h += 360;
  return h;
}
