/// <reference types="node" />
// View-transition polish must keep the art morph as the "lead" (longer,
// spring-eased) and the root crossfade tight so the chrome doesn't drag.
// Under prefers-reduced-motion, all view-transitions collapse to ~instant.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

// Vite's CSS plugin returns an empty string for `?raw` imports on .css files,
// so we read the source directly through Node fs. The triple-slash above
// pulls in @types/node just for this file without polluting the global
// tsconfig types list.
const here = dirname(fileURLToPath(import.meta.url));
const appCssSrc = readFileSync(resolve(here, '../../src/app.css'), 'utf8');

// Section-scope the assertions — anchor on a unique selector that only
// appears in the view-transitions block.
const sectionStart = appCssSrc.indexOf('::view-transition-old(now-playing-art)');
if (sectionStart === -1) {
  throw new Error('view-transitions block missing from app.css');
}
const viewTransitionSection = appCssSrc.slice(sectionStart);

// Captures the body of the first rule whose selector list contains the given
// pseudo-element selector. Robust to selector-grouping (`old(x), new(x) { ... }`).
function ruleBody(selectorFragment: string): string {
  // Standard regex-special-char escape: dot, parens, brackets, braces, etc.
  const escaped = selectorFragment.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(escaped + '[^{]*\\{([^}]+)\\}');
  const m = viewTransitionSection.match(pattern);
  if (!m) throw new Error(`no rule found matching ${selectorFragment}`);
  return m[1];
}

describe('view-transition polish', () => {
  it('uses spring-eased 520ms morph for the now-playing-art', () => {
    // The art is the lead element of the morph — longer + springy easing
    // gives the open/close a physical settle. Both values are deliberate.
    const body = ruleBody('::view-transition-old(now-playing-art)');
    expect(body).toMatch(/animation-duration:\s*520ms/);
    expect(body).toMatch(/animation-timing-function:\s*var\(--ease-spring\)/);
  });

  it('tightens the root crossfade to 220ms with standard ease', () => {
    // Chrome (mini-player, expanded chrome) crossfades on the root transition.
    // Should be snappier than the art morph so the art is what the eye follows.
    const body = ruleBody('::view-transition-old(root)');
    expect(body).toMatch(/animation-duration:\s*220ms/);
    expect(body).toMatch(/animation-timing-function:\s*var\(--ease\)/);
  });

  it('lifts the morph group above other paint layers so drop-shadows survive', () => {
    const body = ruleBody('::view-transition-group(now-playing-art)');
    expect(body).toMatch(/z-index:\s*1/);
  });

  it('flattens all view-transitions to ~instant under prefers-reduced-motion', () => {
    // The reduced-motion override must collapse both art and root transitions
    // or AT users get the spring morph anyway.
    const reducedMotionMatch = viewTransitionSection.match(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*?)\n\}/,
    );
    expect(reducedMotionMatch, 'reduced-motion override missing').not.toBeNull();
    const body = reducedMotionMatch![1];
    expect(body).toMatch(/::view-transition-old\(now-playing-art\)/);
    expect(body).toMatch(/::view-transition-new\(now-playing-art\)/);
    expect(body).toMatch(/::view-transition-old\(root\)/);
    expect(body).toMatch(/::view-transition-new\(root\)/);
    expect(body).toMatch(/animation-duration:\s*0\.01ms/);
  });
});
