// Per-video resume positions for long content (borrowed from Yuzic's playback
// bookmarks). Only videos >= BOOKMARK_MIN_DURATION_S are worth resuming; a
// 3-minute song should always start at 0. Values are plain seconds — never
// URLs, so nothing here is subject to the signed-URL stripping rule.
const KEY = 'hum.bookmarks';
export const BOOKMARK_MIN_DURATION_S = 600;
export const BOOKMARK_END_MARGIN_S = 30;
export const BOOKMARK_MAX_ENTRIES = 200;
// Below this the listener has barely started; resuming at 0:04 is noise.
const MIN_POSITION_S = 5;

type Entry = { pos: number; at: number };

function load(): Record<string, Entry> {
  try {
    const raw = localStorage.getItem(KEY);
    const v: unknown = raw ? JSON.parse(raw) : {};
    if (!v || typeof v !== 'object' || Array.isArray(v)) return {};
    // Drop malformed entries: the eviction sort in saveBookmark reads .at.
    const out: Record<string, Entry> = {};
    for (const [id, e] of Object.entries(v)) {
      if (e && typeof e === 'object' && Number.isFinite((e as Entry).pos) && Number.isFinite((e as Entry).at)) {
        out[id] = { pos: (e as Entry).pos, at: (e as Entry).at };
      }
    }
    return out;
  } catch {
    return {};
  }
}

function persist(all: Record<string, Entry>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    // Storage may be unavailable (private browsing). Best-effort.
  }
}

export function getBookmark(id: string): number | null {
  const e = load()[id];
  return e && Number.isFinite(e.pos) ? e.pos : null;
}

export function clearBookmark(id: string): void {
  const all = load();
  if (!(id in all)) return;
  delete all[id];
  persist(all);
}

export function saveBookmark(id: string, pos: number, dur: number, now: number = Date.now()): void {
  if (!Number.isFinite(dur) || dur < BOOKMARK_MIN_DURATION_S) return;
  if (!Number.isFinite(pos) || pos < MIN_POSITION_S || pos >= dur - BOOKMARK_END_MARGIN_S) {
    clearBookmark(id);
    return;
  }
  const all = load();
  all[id] = { pos, at: now };
  const ids = Object.keys(all);
  if (ids.length > BOOKMARK_MAX_ENTRIES) {
    ids.sort((a, b) => all[a].at - all[b].at);
    for (const old of ids.slice(0, ids.length - BOOKMARK_MAX_ENTRIES)) delete all[old];
  }
  persist(all);
}
