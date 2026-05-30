// Source of truth for the list of available themes.
//
// IMPORTANT: When adding a new theme, you must update FIVE places:
//   1. The ThemeId union below.
//   2. The THEMES array below.
//   3. Create `frontend/src/themes/<id>.css` with the override block
//      `:root[data-theme="<id>"] { ... }`.
//   4. Add `@import './themes/<id>.css';` at the top of
//      `frontend/src/app.css`.
//   5. The validation literal in the inline bootstrap in
//      `frontend/index.html` (it cannot import this module because it
//      runs pre-module-load).

export type ThemeId = 'glass' | 'analog' | 'spotify' | 'youtubemusic';

export type ThemeDescriptor = {
  id: ThemeId;
  name: string;
  description: string;
  /**
   * Hint for the browser's `color-scheme` CSS property and for future
   * `prefers-color-scheme: light` integration. Both shipped themes are
   * dark; the field exists so a future light theme can declare itself
   * without a type-level migration.
   */
  colorScheme: 'dark';
};

export const THEMES = [
  {
    id: 'glass',
    name: 'Glass',
    description: 'Frosted surfaces, coral accent — Hum default.',
    colorScheme: 'dark',
  },
  {
    id: 'analog',
    name: 'Analog Hi-Fi',
    description: 'Brutalist amber, JetBrains Mono.',
    colorScheme: 'dark',
  },
  {
    id: 'spotify',
    name: 'Spotify',
    description: 'Flat dark, signal green, pill CTAs.',
    colorScheme: 'dark',
  },
  {
    id: 'youtubemusic',
    name: 'YouTube Music',
    description: 'Near-black canvas, red accent, Roboto.',
    colorScheme: 'dark',
  },
] as const satisfies readonly ThemeDescriptor[];

export const DEFAULT_THEME: ThemeId = 'glass';

export const THEME_IDS: readonly ThemeId[] = THEMES.map((t) => t.id);
