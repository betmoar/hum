import type { Track } from './types';

// One row per kind of thing the player can hold (borrowed from Yuzic's
// contentKind router). Call sites ask a behaviour question — "is this
// seekable?" — never `t.isLive` directly, so a new kind is one row here
// rather than a branch at every site. Data reads (rendering the LIVE pill,
// building a Track) still read the field.
export type ContentKind = 'vod' | 'live';

type Behaviour = {
  hasDuration: boolean;
  isSeekable: boolean;
  isBookmarkable: boolean;
  isAirplayRoutable: boolean;
  usesHls: boolean;
};

const TABLE: Record<ContentKind, Behaviour> = {
  vod:  { hasDuration: true,  isSeekable: true,  isBookmarkable: true,  isAirplayRoutable: true,  usesHls: false },
  live: { hasDuration: false, isSeekable: false, isBookmarkable: false, isAirplayRoutable: false, usesHls: true },
};

type Kinded = Pick<Track, 'isLive'> | null | undefined;

export function kindOf(t: Kinded): ContentKind | null {
  if (!t) return null;
  return t.isLive ? 'live' : 'vod';
}

function ask(k: keyof Behaviour) {
  return (t: Kinded): boolean => {
    const kind = kindOf(t);
    return kind ? TABLE[kind][k] : false;
  };
}

export const hasDuration = ask('hasDuration');
export const isSeekable = ask('isSeekable');
export const isBookmarkable = ask('isBookmarkable');
export const isAirplayRoutable = ask('isAirplayRoutable');
export const usesHls = ask('usesHls');
