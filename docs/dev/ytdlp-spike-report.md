# yt-dlp spike report

- date: `2026-09-24 13:59 CEST`
- platform: `macOS-15.7.7-x86_64-i386-64bit`
- pytubefix: `10.7.3`
- yt_dlp: `2026.08.19`
- deno: `/usr/local/bin/deno`

## Decision criteria (fixed in the spec before measuring)

| # | Criterion | Result | Pass |
|---|---|---|---|
| D1 | cold video p50 ≤ 2.5 s and ≤ 2.0× pytubefix | ytdlp 2.33 s vs pytubefix 0.34 s | ❌ |
| D2 | cold video p95 ≤ 5.0 s | ytdlp 4.79 s | ✅ |
| D3 | search p50 ≤ 1.3× pytubefix | ytdlp 1.28 s vs pytubefix 5.32 s | ✅ |
| D4 | unexpected outcomes ≤ pytubefix | ytdlp 1 vs pytubefix 14 | ✅ |
| D5 | itag 140/251 on every playable VOD; live has manifest | — | ✅ |

D6 (loudness): yt-dlp does not expose `loudnessDb`; recoverability is a manual note.

## Videos (cold)

| Item | Expect | pytubefix | ytdlp |
|---|---|---|---|
| Rick Astley - Never Gonna Give You Up (`dQw4w9WgXcQ`) | vod | 0.34 s ok ▶ | 4.79 s ok ▶ |
| Luis Fonsi - Despacito (`kJQP7kiw5Fk`) | vod | 0.20 s YOUTUBE_BLOCKED | 2.07 s ok ▶ |
| PSY - Gangnam Style (`9bZkp7q19f0`) | vod | 0.29 s YOUTUBE_BLOCKED | 4.24 s ok ▶ |
| Ed Sheeran - Shape of You (`JGwWNGJdvx8`) | vod | 0.27 s YOUTUBE_BLOCKED | 4.21 s ok ▶ |
| Queen - Bohemian Rhapsody (`fJ9rUzIMcZQ`) | vod | 0.23 s YOUTUBE_BLOCKED | 3.25 s ok ▶ |
| Nirvana - Smells Like Teen Spirit (`hTWKbfoikeg`) | vod | 0.28 s YOUTUBE_BLOCKED | 2.32 s ok ▶ |
| Adele - Hello (`YQHsXMglC9A`) | vod | 0.22 s YOUTUBE_BLOCKED | 2.01 s ok ▶ |
| Wiz Khalifa - See You Again (`RgKAFK5djSk`) | vod | 0.25 s YOUTUBE_BLOCKED | 2.33 s ok ▶ |
| Mark Ronson - Uptown Funk (`OPf0YbXqDm0`) | vod | 0.25 s YOUTUBE_BLOCKED | 2.32 s ok ▶ |
| Alan Walker - Faded (`60ItHLz5WEA`) | vod | 0.30 s YOUTUBE_BLOCKED | 2.57 s ok ▶ |
| long VOD 2h (Brian Culbertson live, verified 2026-09-24) (`lQ0iqwatAl8`) | vod | 0.25 s YOUTUBE_BLOCKED | 2.08 s ok ▶ |
| long VOD 2h (Andrea Bocelli, verified 2026-09-24) (`UVByTzYL8KI`) | vod | 0.33 s YOUTUBE_BLOCKED | 2.00 s ok ▶ |
| long VOD 1h37 (MEUTE Live in Paris, verified 2026-09-24) (`2loN0JFZa0Y`) | vod | 0.20 s YOUTUBE_BLOCKED | 2.55 s ok ▶ |
| Lofi Girl radio (live, verified 2026-09-24) (`7NOSDKb0HlU`) | live | 0.27 s YOUTUBE_BLOCKED | 1.93 s ok |
| synthwave radio (live, verified 2026-09-24) (`4xDzrJKXOOY`) | live | 0.26 s YOUTUBE_BLOCKED | 1.97 s ok |
| nonexistent id (expected VIDEO_UNAVAILABLE) (`aaaaaaaaaaa`) | error | 0.17 s VIDEO_UNAVAILABLE | 1.05 s UPSTREAM_FAILURE |
| age-restricted (verified: Sign in to confirm your age) (`HtVdAasjOgU`) | error | 0.45 s YOUTUBE_BLOCKED | 3.92 s ok |

## Searches (cold)

| Query | pytubefix | ytdlp | Titled hits (pytubefix / ytdlp) |
|---|---|---|---|
| rick astley never gonna give you up | 7.54 s, 19 hits | 1.12 s, 20 hits | 5% / 95% |
| tomorrowland | 5.17 s, 18 hits | 1.96 s, 20 hits | 0% / 90% |
| daft punk | 5.23 s, 17 hits | 1.83 s, 20 hits | 0% / 100% |
| vernki | 9.90 s, 13 hits | 1.28 s, 20 hits | 0% / 90% |
| lofi radio | 5.32 s, 20 hits | 1.55 s, 11 hits | 0% / 100% |
| news live | 5.34 s, 20 hits | 0.73 s, 20 hits | 0% / 100% |
