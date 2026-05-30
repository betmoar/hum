// Persisted recent-searches list used by the Discover empty state.
// Pure functions modulo a single localStorage side effect — easy to test.

import { migrateLegacyKeys } from './migrateLegacy';

// Rename legacy `streamtube.*` keys before any reads. Idempotent — safe to
// call from both this module and store.svelte.ts at module load.
migrateLegacyKeys();

const KEY = 'hum.recent_searches';
export const MAX_RECENT = 10;

/** Load the recent-searches list. Returns [] for any unreadable, malformed,
 *  or non-array payload — never throws. Caps the result at MAX_RECENT in
 *  case storage was hand-edited or migrated from an older format. */
export function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is string => typeof x === 'string').slice(0, MAX_RECENT);
  } catch {
    return [];
  }
}

/** Returns a new list with `q` placed at the front (case-insensitive
 *  dedup, capped at MAX_RECENT) and persists it. Pure with respect to the
 *  input array; a no-op when `q` is empty or whitespace. localStorage
 *  failures are swallowed silently — in private-browsing mode the list
 *  still updates in memory for the lifetime of the session. */
export function withRecent(current: readonly string[], q: string): string[] {
  const trimmed = q.trim();
  if (!trimmed) return [...current];
  const next = [
    trimmed,
    ...current.filter((r) => r.toLowerCase() !== trimmed.toLowerCase()),
  ].slice(0, MAX_RECENT);
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // best-effort persist
  }
  return next;
}
