export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '--:--';
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const pad = (n: number) => n.toString().padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(ss)}` : `${m}:${pad(ss)}`;
}

export function formatViewCount(views: number | null | undefined): string {
  if (views == null || !Number.isFinite(views)) return '';
  if (views >= 1_000_000_000) return `${(views / 1_000_000_000).toFixed(1)}B`;
  if (views >= 1_000_000) return `${(views / 1_000_000).toFixed(1)}M`;
  if (views >= 1_000) return `${(views / 1_000).toFixed(1)}K`;
  return views.toString();
}

export function formatBitrate(bps: number): string {
  return `${Math.round(bps / 1000)} kbps`;
}

// YouTube titles routinely contain runs of whitespace
// (e.g. "(Official Video)  (4K Remaster)" — double-space). Collapse them
// to a single space so display-serif rendering doesn't expose the gap.
//
// Note: a whitespace-only or empty input returns an empty string. Callers
// at the API boundary leave the empty title on the response object; the UI
// treats an empty title as "no title" (renders nothing). YouTube doesn't
// ship empty titles in practice, so this is documented rather than guarded.
export function normalizeTitle(s: string): string {
  return s.replace(/\s+/g, ' ').trim();
}
