import { describe, it, expect, beforeEach, vi } from 'vitest';

// migrateLegacyKeys() sets a module-private `didRun` flag on first call, so
// every test must import a FRESH module instance (vi.resetModules + dynamic
// import) or all calls after the first are silently no-ops.

beforeEach(() => {
  localStorage.clear();
  vi.resetModules();
});

describe('migrateLegacyKeys', () => {
  it('copies legacy keys to the hum.* keyspace and removes the legacy key', async () => {
    localStorage.setItem('streamtube.bearer', 'tok');
    localStorage.setItem('streamtube.recent_searches', JSON.stringify(['a', 'b']));
    const { migrateLegacyKeys } = await import('../../src/lib/migrateLegacy');

    migrateLegacyKeys();

    expect(localStorage.getItem('hum.bearer')).toBe('tok');
    expect(localStorage.getItem('hum.recent_searches')).toBe(JSON.stringify(['a', 'b']));
    expect(localStorage.getItem('streamtube.bearer')).toBeNull();
    expect(localStorage.getItem('streamtube.recent_searches')).toBeNull();
  });

  it('new-key-wins: an existing hum.* key is not clobbered by legacy data', async () => {
    localStorage.setItem('streamtube.queue', 'legacy-queue');
    localStorage.setItem('hum.queue', 'fresh-queue');
    const { migrateLegacyKeys } = await import('../../src/lib/migrateLegacy');

    migrateLegacyKeys();

    expect(localStorage.getItem('hum.queue')).toBe('fresh-queue');
    // Legacy key is still removed even when the new key already existed.
    expect(localStorage.getItem('streamtube.queue')).toBeNull();
  });

  it('is idempotent: a second call is a no-op (legacy keys already gone)', async () => {
    localStorage.setItem('streamtube.bearer', 'tok');
    const { migrateLegacyKeys } = await import('../../src/lib/migrateLegacy');

    migrateLegacyKeys();
    expect(localStorage.getItem('hum.bearer')).toBe('tok');
    const humBearerBefore = localStorage.getItem('hum.bearer');

    migrateLegacyKeys(); // second call — must not throw, must not change state
    expect(localStorage.getItem('hum.bearer')).toBe(humBearerBefore);
    expect(localStorage.getItem('streamtube.bearer')).toBeNull();
  });

  it('propagates malformed legacy JSON verbatim (does not crash or wipe it)', async () => {
    const malformed = '{not valid json';
    localStorage.setItem('streamtube.queue', malformed);
    const { migrateLegacyKeys } = await import('../../src/lib/migrateLegacy');

    expect(() => migrateLegacyKeys()).not.toThrow();

    // The bad payload survives into the new key verbatim — migration is a
    // blind string copy; it must not parse, "repair", or drop the value.
    expect(localStorage.getItem('hum.queue')).toBe(malformed);
    expect(localStorage.getItem('streamtube.queue')).toBeNull();
  });

  it('no-ops cleanly when there is nothing to migrate', async () => {
    const { migrateLegacyKeys } = await import('../../src/lib/migrateLegacy');

    expect(() => migrateLegacyKeys()).not.toThrow();
    expect(localStorage.getItem('hum.bearer')).toBeNull();
    expect(localStorage.getItem('hum.queue')).toBeNull();
  });
});
