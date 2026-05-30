// Living-glass motion must be gated behind `prefers-reduced-motion: no-preference`.
// Users who request reduced motion should see the same chromatic glass system
// without the slow drift / breathe animations.

import { describe, it, expect, afterEach } from 'vitest';
// Vite's ?raw query loads the file as a string at test-time — no Node fs APIs
// needed, which keeps the tsconfig free of @types/node just for one test.
import appSvelteSrc from '../../src/App.svelte?raw';

function extractFirstStyleBlock(src: string): string {
  const m = src.match(/<style>([\s\S]*?)<\/style>/);
  if (!m) throw new Error('No <style> block found in App.svelte');
  return m[1];
}

const livingGlassCss = extractFirstStyleBlock(appSvelteSrc);

describe('living-glass motion', () => {
  let mounted: HTMLStyleElement | null = null;

  afterEach(() => {
    if (mounted) {
      mounted.remove();
      mounted = null;
    }
  });

  it('declares the three named keyframes used by the drift + breathe system', () => {
    expect(livingGlassCss).toMatch(/@keyframes\s+art-drift\b/);
    expect(livingGlassCss).toMatch(/@keyframes\s+ambient-drift\b/);
    expect(livingGlassCss).toMatch(/@keyframes\s+wash-breathe\b/);
  });

  it('gates all art-stage animations behind prefers-reduced-motion: no-preference', () => {
    mounted = document.createElement('style');
    mounted.textContent = livingGlassCss;
    document.head.appendChild(mounted);
    const sheet = mounted.sheet;
    expect(sheet, 'style element produced no CSSStyleSheet').not.toBeNull();

    const topLevelRules = Array.from(sheet!.cssRules);

    const reducedMotionGuard = topLevelRules.find(
      (r): r is CSSMediaRule =>
        r instanceof CSSMediaRule &&
        /prefers-reduced-motion\s*:\s*no-preference/i.test(r.conditionText ?? r.media.mediaText),
    );
    expect(
      reducedMotionGuard,
      'expected an @media (prefers-reduced-motion: no-preference) block in App.svelte styles',
    ).toBeDefined();

    const guardedSelectors = Array.from(reducedMotionGuard!.cssRules)
      .filter((r): r is CSSStyleRule => r instanceof CSSStyleRule)
      .map((r) => r.selectorText);

    expect(guardedSelectors).toEqual(
      expect.arrayContaining(['.art-layer', '.art-ambient', '.art-wash']),
    );

    // Critically: no .art-* rule may declare `animation` *outside* the guard.
    // If someone moves a rule out of the media block, reduced-motion users would
    // get the animation anyway — that's the regression this test exists to catch.
    for (const rule of topLevelRules) {
      if (!(rule instanceof CSSStyleRule)) continue;
      if (!/\.art-(layer|ambient|wash)\b/.test(rule.selectorText)) continue;
      expect(
        rule.style.getPropertyValue('animation'),
        `${rule.selectorText} declares 'animation' outside the prefers-reduced-motion guard`,
      ).toBe('');
      expect(
        rule.style.getPropertyValue('animation-name'),
        `${rule.selectorText} declares 'animation-name' outside the prefers-reduced-motion guard`,
      ).toBe('');
    }
  });

  it('keeps drift amplitude within a subliminal sub-2% positional range', () => {
    // Pulls every translate3d() argument out of the @keyframes blocks and asserts
    // none of them exceed 2% — this is the design contract: living, not lively.
    const translateArgs = [...livingGlassCss.matchAll(/translate3d\(\s*([^)]+)\)/g)].flatMap((m) =>
      m[1].split(',').map((s) => s.trim()),
    );

    const percentages = translateArgs
      .filter((arg) => arg.endsWith('%'))
      .map((arg) => Math.abs(parseFloat(arg)));

    expect(percentages.length, 'expected translate3d() calls inside keyframes').toBeGreaterThan(0);
    for (const pct of percentages) {
      expect(pct).toBeLessThanOrEqual(2);
    }
  });
});
