import { describe, it, expect } from 'vitest';
import { formatDuration, formatViewCount, formatBitrate, normalizeTitle } from '../../src/lib/format';

describe('formatDuration', () => {
  it('zero', () => expect(formatDuration(0)).toBe('0:00'));
  it('under a minute', () => expect(formatDuration(45)).toBe('0:45'));
  it('exactly a minute', () => expect(formatDuration(60)).toBe('1:00'));
  it('several minutes', () => expect(formatDuration(213)).toBe('3:33'));
  it('over an hour', () => expect(formatDuration(3661)).toBe('1:01:01'));
  it('exactly an hour', () => expect(formatDuration(3600)).toBe('1:00:00'));
  it('handles undefined/null gracefully', () => {
    expect(formatDuration(null)).toBe('--:--');
    expect(formatDuration(undefined)).toBe('--:--');
  });
});

describe('formatViewCount', () => {
  it('under 1k', () => expect(formatViewCount(999)).toBe('999'));
  it('thousands', () => expect(formatViewCount(15_400)).toBe('15.4K'));
  it('millions', () => expect(formatViewCount(1_400_000_000)).toBe('1.4B'));
  it('null', () => expect(formatViewCount(null)).toBe(''));
  it('undefined', () => expect(formatViewCount(undefined)).toBe(''));
});

describe('formatBitrate', () => {
  it('kbps', () => expect(formatBitrate(128_000)).toBe('128 kbps'));
  it('rounds', () => expect(formatBitrate(160_500)).toBe('161 kbps'));
});

describe('normalizeTitle', () => {
  it('collapses the YouTube double-space pattern', () => {
    expect(normalizeTitle('Never Gonna Give You Up (Official Video)  (4K Remaster)'))
      .toBe('Never Gonna Give You Up (Official Video) (4K Remaster)');
  });
  it('collapses any run of internal whitespace', () => {
    expect(normalizeTitle('a   b\t\tc\n\nd')).toBe('a b c d');
  });
  it('trims surrounding whitespace', () => {
    expect(normalizeTitle('  hello  ')).toBe('hello');
  });
  it('leaves single-spaced titles untouched', () => {
    expect(normalizeTitle('Plain title with spaces')).toBe('Plain title with spaces');
  });
  it('handles empty string', () => {
    expect(normalizeTitle('')).toBe('');
  });
  it('whitespace-only input normalises to empty string', () => {
    // Documented behaviour: callers treat empty as "no title". YouTube
    // doesn't ship whitespace-only titles in practice.
    expect(normalizeTitle('   \t  \n  ')).toBe('');
  });
});
