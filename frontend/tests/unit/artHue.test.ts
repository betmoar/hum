import { describe, it, expect } from 'vitest';
import { rgbToHue } from '../../src/lib/artHue.svelte';

describe('rgbToHue', () => {
  it('pure red is 0', () => expect(rgbToHue(255, 0, 0)).toBe(0));
  it('pure green is 120', () => expect(rgbToHue(0, 255, 0)).toBe(120));
  it('pure blue is 240', () => expect(rgbToHue(0, 0, 255)).toBe(240));
  it('greyscale returns null (no meaningful hue)', () => expect(rgbToHue(128, 128, 128)).toBeNull());
  it('pure black returns null', () => expect(rgbToHue(0, 0, 0)).toBeNull());
  it('pure white returns null', () => expect(rgbToHue(255, 255, 255)).toBeNull());
});
