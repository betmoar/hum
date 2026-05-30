/**
 * One-time localStorage rename from the StreamTube era (`streamtube.*`) to
 * the Hum-branded keys (`hum.*`). Runs at module load, before the store
 * reads its initial state. Safe to invoke repeatedly: each key only
 * migrates if the legacy key exists AND the new key does not — anything
 * already on the new keyspace wins.
 *
 * Delete this module (and its imports) once the rename has been live long
 * enough that returning users have all upgraded.
 */

const LEGACY_TO_NEW: ReadonlyArray<readonly [string, string]> = [
  ['streamtube.bearer',          'hum.bearer'],
  ['streamtube.queue',           'hum.queue'],
  ['streamtube.recent_searches', 'hum.recent_searches'],
];

let didRun = false;

export function migrateLegacyKeys(): void {
  if (didRun) return;
  didRun = true;
  try {
    for (const [legacy, next] of LEGACY_TO_NEW) {
      const oldVal = localStorage.getItem(legacy);
      if (oldVal === null) continue;
      if (localStorage.getItem(next) === null) {
        localStorage.setItem(next, oldVal);
      }
      localStorage.removeItem(legacy);
    }
  } catch {
    // Storage may be unavailable (private browsing, quota). Best-effort.
  }
}
