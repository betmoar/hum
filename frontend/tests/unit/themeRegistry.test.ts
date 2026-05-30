import { describe, it, expect } from 'vitest';
import { THEMES, THEME_IDS, DEFAULT_THEME } from '../../src/themes/registry';

describe('theme registry', () => {
  it('ships the four themes in registration order', () => {
    expect(THEME_IDS).toEqual(['glass', 'analog', 'spotify', 'youtubemusic']);
  });

  it('has Glass as the default theme', () => {
    expect(DEFAULT_THEME).toBe('glass');
    expect(THEME_IDS).toContain(DEFAULT_THEME);
  });

  it('every theme has a non-empty name and description', () => {
    for (const t of THEMES) {
      expect(t.name.trim().length).toBeGreaterThan(0);
      expect(t.description.trim().length).toBeGreaterThan(0);
    }
  });

  it('THEME_IDS has no duplicates', () => {
    expect(new Set(THEME_IDS).size).toBe(THEME_IDS.length);
  });
});
