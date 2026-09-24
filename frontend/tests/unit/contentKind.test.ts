import { describe, it, expect } from 'vitest';
import { kindOf, hasDuration, isSeekable, isBookmarkable, isAirplayRoutable, usesHls } from '../../src/lib/contentKind';

const vod = { isLive: false } as any;
const live = { isLive: true } as any;
const legacy = {} as any;

describe('contentKind', () => {
  it('classifies', () => {
    expect(kindOf(vod)).toBe('vod');
    expect(kindOf(live)).toBe('live');
    expect(kindOf(legacy)).toBe('vod');
    expect(kindOf(null)).toBeNull();
  });

  it('vod row', () => {
    for (const f of [hasDuration, isSeekable, isBookmarkable, isAirplayRoutable]) expect(f(vod)).toBe(true);
    expect(usesHls(vod)).toBe(false);
  });

  it('live row', () => {
    for (const f of [hasDuration, isSeekable, isBookmarkable, isAirplayRoutable]) expect(f(live)).toBe(false);
    expect(usesHls(live)).toBe(true);
  });

  it('null is false everywhere', () => {
    for (const f of [hasDuration, isSeekable, isBookmarkable, isAirplayRoutable, usesHls]) expect(f(null)).toBe(false);
  });
});
