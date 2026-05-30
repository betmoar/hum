// Mirror of backend Pydantic shapes (app/models.py).
// Hand-maintained; if backend changes, update here.

export type SearchKind = 'video' | 'channel' | 'playlist';

export type Quality = 'hi' | 'low';

export type SearchHit = {
  kind: SearchKind;
  id: string;
  title: string;
  author?: string | null;
  thumbnail_url: string;
  duration_seconds?: number | null;
  video_count?: number | null;
  is_live?: boolean | null;
};

export type SearchResponse = {
  query: string;
  items: SearchHit[];
};

export type AudioFormat = {
  itag: number;
  mime_type: string;
  bitrate: number;
  codec: string;
  sample_rate?: number | null;
  channels?: number | null;
  url: string;
  hls_url?: string | null;
};

export type VideoFormat = {
  itag: number;
  mime_type: string;
  bitrate: number;
  codec: string;
  width: number;
  height: number;
  fps?: number | null;
  has_audio: boolean;
  url: string;
};

export type VideoDetails = {
  video_id: string;
  title: string;
  description?: string | null;
  author: string;
  channel_id: string;
  duration_seconds: number;
  view_count?: number | null;
  thumbnail_url: string;
  audio_formats: AudioFormat[];
  video_formats: VideoFormat[];
  is_live?: boolean | null;
  live_stream_url?: string | null;
};

export type ChannelInfo = {
  channel_id: string;
  title: string;
  description?: string | null;
  subscriber_count?: number | null;
  thumbnail_url: string;
};

export type PlaylistItem = {
  video_id: string;
  title: string;
  author?: string | null;
  duration_seconds?: number | null;
  thumbnail_url: string;
};

export type PlaylistInfo = {
  playlist_id: string;
  title: string;
  author?: string | null;
  video_count: number;
  items: PlaylistItem[];
};

// Frontend-only type used by the player + queue.
export type Track = {
  videoId: string;
  title: string;
  author: string;
  durationSeconds: number;
  thumbnailUrl: string;
  audioUrl: string;
  hlsUrl?: string;
  itag: number;
  // Optional metadata surfaced on the expanded NowPlaying view. Both come from
  // VideoDetails at the moment buildTrack runs; absent for rehydrated tracks
  // older than this field, which is fine — the metadata strip degrades.
  viewCount?: number;
  bitrate?: number;
  // Quality tier the user selected for this track. Persisted.
  qualityTier?: Quality;
  // Whether this track is a livestream. Persisted; defaults to false on load.
  isLive?: boolean;
  // Ephemeral: full audio_formats list captured at build time, used by
  // Player.svelte's codec-fallback recovery. NOT persisted to localStorage —
  // stripped during the store's #flush().
  _formats?: AudioFormat[];
  // Signed /api/live/{id}/manifest.m3u8 URL for live tracks. Empty/undefined
  // for VOD. Stripped on persistence (see store.svelte.ts #flush).
  liveStreamUrl?: string;
};
