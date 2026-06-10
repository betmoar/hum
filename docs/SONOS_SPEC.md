# Hum → Sonos Integration Spec

**Status:** audited against the Hum codebase at `c68470e` (Hum 0.1.0). This
revision corrects the original draft where the repo had moved past the README
it was written from, and resolves the open decisions the code already answers.

**Goal:** Make Hum (self-hosted YouTube audio streamer) appear as a first-class
music source *inside the Sonos app* — browsable, searchable, queueable —
without writing a Sonos SMAPI server from scratch.

**Strategy:** Implement a **Subsonic-compatible API adapter** in front of Hum,
then point **bonob** (an existing, mature SMAPI⇄Subsonic bridge) at it. bonob
handles all Sonos-facing complexity; we only build the Hum→Subsonic translation.

```
Sonos app  ─SMAPI(SOAP)─►  bonob  ─Subsonic API─►  hum-subsonic-shim  ─►  Hum backend  ─►  YouTube
   │                         │                          │                     │
 controller            (unmodified,                (new component         (existing FastAPI,
 (phone, out          mature project)              we build)              pytubefix, signed URLs)
  of audio path)
                                          Sonos speaker pulls audio directly ◄─── shim /stream
```

The phone is only a controller. The **Sonos speaker fetches audio directly**
from the shim's `/stream` endpoint — true handoff, phone can sleep/leave.

-----

## 1. Architecture decision record

### Why the shim-over-bonob path (Option A) instead of a native SMAPI server (Option B)

|Factor                                    |Shim + bonob (chosen)                       |From-scratch SMAPI                     |
|------------------------------------------|--------------------------------------------|---------------------------------------|
|Sonos SOAP / auth / S2 cloud handling     |Handled by bonob                            |We build & maintain it                 |
|Browse/search/art/now-playing in Sonos app|Inherited from bonob                        |We build it                            |
|API surface to implement                  |Subsonic subset (well-documented, REST/JSON)|SMAPI (SOAP, fiddlier)                 |
|Local test client before Sonos            |**Amperfy** (already in use)                |None — must test against Sonos directly|
|Reuse of existing stack                   |Aligns with existing Gonic/Subsonic setup   |Parallel new stack                     |
|Long-term maintenance                     |Track bonob releases                        |Solo-maintain SMAPI quirks             |

The deciding factor: an existing Gonic+Amperfy setup means a Subsonic shim can
be validated end-to-end with a trusted client (Amperfy) **before Sonos ever
sees it**. That feedback loop is worth more than the control gained by going
native.

### Accepted constraints

- Sonos network is already internet-connected; the S2 "expose to internet"
  requirement is therefore an accepted cost, not a blocker. (See §6.)
- Hum is pytubefix-based and inherently ToS-fragile. This integration does not
  change that; it inherits it.

### Audit deltas from the original draft

1. **Hum exposes AAC, not just Opus.** `AudioFormat.codec` is `"aac" | "opus"`;
   the adapter maps `mp4a → aac` and signs an `hls_url` for `audio/mp4`
   formats. The transcode strategy is therefore **remux-first** (§4), which
   downgrades the draft's biggest technical risk.
2. **Hum has live-stream and radio surfaces** (`/api/radio`, `/api/live/...`,
   `/proxy/live-segment/...`). Live content is **out of scope** for the shim:
   it doesn't fit the Subsonic track model and can't be transcoded the same
   way. `search3` must filter live hits out (§3.4).
3. **Hum has zero persistence.** No play history, no favourites, in-memory
   caches only. "Recently played" and `star`/`unstar` are shim-side features
   or omitted (§3.2–3.3, §9).
4. **Internal upstream URL cache is 1 h** (capped by YouTube's own `expire=`),
   not the 5 min the old README claimed. Signed *proxy* URL TTL remains 6 h.
   Latency budgeting in §4/§5 reflects this.
5. **`/api/video/{id}` is the expensive call** (full pytubefix extraction,
   seconds when cold; single-flighted and cached inside Hum). The shim must
   cache its responses (§5) so `getCoverArt` and repeat `stream` calls don't
   re-trigger extraction.

-----

## 2. Component inventory

|Component            |Status      |Role                                                      |
|---------------------|------------|----------------------------------------------------------|
|Hum backend          |Exists      |YouTube search + signed, range-aware proxy URLs; AAC+Opus formats; live/radio (unused here)|
|Gonic                |Exists      |Current Subsonic server feeding Amperfy (untouched)       |
|Amperfy              |Exists      |Subsonic client — used here as the shim's **test harness**|
|**hum-subsonic-shim**|**To build**|Translates Subsonic API → Hum API; remuxes/transcodes audio|
|bonob                |To deploy   |SMAPI⇄Subsonic bridge; registers Hum as a Sonos source    |
|Sonos                |Exists      |Endpoint; speakers pull audio directly from the shim      |

Key point: the shim is a **separate** Subsonic endpoint from Gonic. Do not graft
YouTube content into the Gonic library. bonob supports multiple registrations;
Hum becomes its own Sonos source alongside the existing music.

**Shim location & stack (resolved):** Python/FastAPI, living in the Hum repo as
a sibling service. The shim reuses Hum's idioms — ports-and-adapters layout,
`StreamingResponse` lifecycle handling modelled on `app/proxy/_common.py`
(`body_iterator`'s guaranteed-close pattern is exactly what the ffmpeg pipe
needs), pydantic-settings config, same deploy story.

-----

## 3. The shim: Subsonic API surface to implement

bonob calls a subset of the Subsonic API. Implement only what it touches. All
Subsonic endpoints live under `/rest/` and accept `u`, `p`/`t`+`s`, `v`, `c`,
`f=json` query params. Respond in JSON (`subsonic-response` envelope).

### 3.1 Must-have (minimum playable)

|Subsonic endpoint|Maps to Hum                             |Notes                                                            |
|-----------------|----------------------------------------|-----------------------------------------------------------------|
|`ping`           |—                                       |Health/auth check. Return OK envelope.                           |
|`getLicense`     |—                                       |Return `valid=true`.                                             |
|`stream?id=`     |Hum `/api/video/{id}` → signed proxy URL|**Remux/transcode to a Sonos-safe format** (see §4).             |
|`getCoverArt?id=`|see §3.5                                |Shim fetches and re-serves bytes; never redirects the client.    |
|`search3?query=` |Hum `/api/search`                       |Map YouTube results → Subsonic `song`/`album`/`artist` shapes. **Filter live hits** (§3.4).|

### 3.2 Browsing (makes it feel native in the Sonos app)

|Subsonic endpoint                 |Maps to / strategy                                                   |
|----------------------------------|---------------------------------------------------------------------|
|`getMusicFolders`                 |Return one synthetic folder, e.g. "Hum".                             |
|`getIndexes` / `getArtists`       |Synthetic top-level: "Search", "Playlists". ("Recently Played" only if built shim-side — Hum has no history.)|
|`getPlaylists` / `getPlaylist?id=`|Hum `/api/playlist/{id}` → Subsonic playlist.                        |
|`getAlbumList2?type=`             |Hum has no history; return empty for `recent`/`frequent` unless the shim records its own.|
|`getArtist` / `getAlbum`          |Synthesize from playlist/channel (`/api/channel/{id}`) where it makes sense.|

### 3.3 Optional / nice-to-have

|Subsonic endpoint|Purpose                                                           |
|-----------------|------------------------------------------------------------------|
|`scrobble`       |bonob reports now-playing/scrobble; accept and no-op or log. Doubles as the data source if the shim grows its own "recently played".|
|`star` / `unstar`|Favourites from the Sonos app — requires shim-side storage (Hum stores nothing).|
|`getGenres`      |Skip unless you want genre browsing.                              |

### 3.4 The modelling problem (the real design work)

Subsonic assumes a **library** (artists → albums → tracks). Hum is **search +
stream**. You are mapping a search engine onto a library shape. Decide the
synthetic hierarchy up front:

- **Search** as the primary entry (Sonos search box → `search3` → Hum search).
  Pass `category=music` to Hum's search for better signal where appropriate.
- **Playlists** map cleanly (Hum already has `/api/playlist/{id}`).
- A single video → model as a single-track "album" so it slots into Subsonic's
  album/track expectations.
- **Live hits must be excluded.** `SearchHit.is_live` is unreliable from
  pytubefix (often `None` for live streams); use the inverse of the heuristic
  already proven in `app/api/radio.py:_looks_live` — zero/missing duration
  means live, so drop the hit. Concretely:
  ```python
  results = [h for h in raw if not _looks_live(h)]
  ```
  (`radio.py` keeps hits where `_looks_live` is True; `search3` drops them.)
  A "Radio" browse entry for live streams is a possible later phase, not Phase 1/2.

Stable ID scheme is critical: Subsonic IDs must round-trip to YouTube IDs.
Prefixing: `vid:<ytid>`, `pl:<ytplaylistid>`, `art:<channelid>` so the shim can
route any incoming `id` back to the right Hum call. Note Hum validates video
IDs as exactly 11 chars of `[A-Za-z0-9_-]`; playlist IDs 2–64 chars; channel
IDs 5–64 chars — the shim should reject malformed IDs before calling Hum.

### 3.5 Cover art strategy

Two sources, both server-side (the Sonos client never sees a YouTube URL):

- **Search hits / playlist items** carry raw `i.ytimg.com` thumbnail URLs in
  Hum's responses. The shim may fetch these directly and re-serve the bytes —
  cheap, no extraction triggered.
- **Video details** (`/api/video/{id}`) return a **signed**
  `/proxy/thumbnail/{id}` URL. Use this when the shim already has a cached
  details response; do **not** call `/api/video/{id}` solely for cover art —
  that triggers a full pytubefix extraction.

Resize/normalize to the `size=` Subsonic param as needed; cache aggressively.

-----

## 4. Audio delivery: remux first, transcode as fallback

**The original draft assumed Opus/WebM only and made mp3 re-encode the plan of
record. The codebase says otherwise:** Hum surfaces YouTube's AAC (`audio/mp4`,
itag-140 class) formats with `codec="aac"`, alongside Opus. Sonos plays AAC
natively. So:

### Mode 1 (default): AAC remux — `ffmpeg -c copy`

```
Sonos GET /rest/stream?id=vid:<ytid>
  → shim calls Hum /api/video/<ytid>  (cached; picks audio format with codec=="aac")
  → shim spawns:  ffmpeg -i <signed_proxy_url> -c:a copy -f mp4 -movflags frag_keyframe+empty_moov -   (pipe)
  → shim streams stdout to Sonos with Content-Type: audio/mp4
```

Near-zero CPU, no quality loss, first byte limited only by Hum URL resolution.
Fragmented MP4 (fMP4) is preferred over ADTS: it preserves the timing atom so
Sonos can display track length and seek, and is the same container Hum's own
HLS path produces (`app/api/hls.py`). ADTS is a secondary experiment — try it
if fMP4 causes buffering issues, but expect no seek bar. Mode 2 is the last
resort.

**Mode 1 container preference order:**
1. `-f mp4 -movflags frag_keyframe+empty_moov` → `Content-Type: audio/mp4` (start here)
2. `-f adts` → `Content-Type: audio/aac` (try if fMP4 causes issues)
3. Mode 2 (mp3 re-encode) if both AAC containers are rejected

### Mode 2 (fallback): mp3 re-encode

```
  → shim spawns:  ffmpeg -i <signed_proxy_url> -f mp3 -b:a 256k -   (pipe)
  → Content-Type: audio/mpeg
```

Used when no AAC format exists for a video (rare) or if Sonos rejects the
remuxed AAC in Amperfy/Sonos testing. mp3 CBR 256k, no exotic sample rates.

### Requirements / gotchas (both modes)

- **Range requests:** Sonos issues HTTP range requests for seeking. Live ffmpeg
  pipes are not seekable. Options:
  - (a) Ignore ranges, stream straight through (works for play-through; seeking
    may be degraded). Simplest. Start here.
  - (b) Pre-transcode to a temp file, then serve with proper range support.
    Adds latency + disk, gains seeking. Optimize to this later.
  - (c) *Possible Mode-1-only shortcut, verify before relying on it:* since
    remux is byte-cheap, a ranged request can be served by restarting the remux
    and discarding output up to the offset — still (a)-class simplicity with
    approximate seek support.
- **Container/timing:** fMP4/ADTS/mp3 over a chunked pipe generally works; some
  renderers want `Content-Length`. If Sonos balks, fall back to temp-file mode (b).
- **Process lifecycle:** kill ffmpeg when Sonos disconnects (skip/stop) or you
  leak processes. Wire to the request lifecycle — follow the
  `app/proxy/_common.py` `body_iterator` pattern: a generator whose `finally`
  reaps the process, wrapped in `StreamingResponse`.
- **Latency:** first-byte latency = Hum `/api/video` call (seconds when the
  extraction is cold; Hum single-flights and caches upstream URLs for up to
  1 h) + ffmpeg spin-up (negligible in copy mode). The shim's own details
  cache (§5) keeps the warm path fast; consider prefetching the *next* queue
  item's details on `stream` calls.

Test this in isolation before involving Sonos: curl the shim's `/stream` into
a file, inspect with `ffprobe`, play locally — then Amperfy — then Sonos.

-----

## 5. URL signing, TTLs, and the shim's cache

Three clocks to keep straight:

|Layer                                |TTL          |Where               |
|-------------------------------------|-------------|--------------------|
|Hum signed proxy URLs (`exp`/`sig`)  |6 h default (`STREAM_URL_TTL_SECONDS`)|minted by `/api/video/{id}`, per-itag|
|Hum internal upstream-URL cache      |≤ 1 h, also capped by YouTube's `expire=`|inside `app/adapters/youtube.py`; transparent to the shim|
|Shim details cache (to build)        |`min(1800, exp − now − 60)` s|shim-side|

- Hum mints signed proxy URLs per-itag with `exp`/`sig` query params. The
  **shim** consumes those internally and re-exposes its own `/stream` to Sonos
  — Sonos never sees a Hum signed URL or a raw YouTube CDN URL. (Preserves Hum
  invariant #3.)
- The shim's own `/stream` URL is what bonob/Sonos hold; it embeds only the
  `vid:` ID, so it never expires. The shim mints/refreshes Hum URLs per stream
  request — the 6 h TTL is never the limiting factor, including for gapless/
  queued playback.
- **Cache `/api/video/{id}` responses in the shim** (metadata + signed URLs +
  signed thumbnail URL). This is what keeps `getCoverArt`, repeated `stream`
  calls, and queue prefetch from hammering pytubefix extraction. Evict each
  entry using `ttl = min(1800, exp − now − 60)` — the 60 s safety margin
  prevents serving an already-expired signed URL to ffmpeg mid-stream.
- The shim holds Hum's `API_BEARER_TOKEN` server-side; it is never exposed to
  bonob/Sonos.

-----

## 6. S1 vs S2 deployment (network exposure)

bonob behaves differently by Sonos generation:

- **S1:** works fully **local** — bonob only needs to be reachable by Sonos
  devices on the LAN (`BNB_URL` = LAN IP). No internet exposure.
- **S2 (since May 2024):** bonob **must be reachable from the internet** because
  Sonos's cloud calls into it. `BNB_URL` must be a public DNS name (HTTPS).

Since the Sonos network is already internet-connected, the S2 path is acceptable
here. Hardening checklist for S2:

- Expose **only bonob** publicly (HTTPS/443). Keep the shim and Hum on the LAN,
  reachable by bonob but **not** from the internet. (Hum already defaults to
  binding `127.0.0.1`; the shim must be reachable by the Sonos *speakers* on
  the LAN for `/stream`, but not by the internet.)
- Restrict the firewall to Sonos's published IP ranges where possible.
- Terminate TLS at a reverse proxy (Caddy/nginx/Cloudflare Tunnel — bonob docs
  confirm cloudflared works).
- Long random `BNB_SECRET`.
- Note the trust boundary: bonob is the only internet-facing surface; the
  YouTube-extracting shim + Hum stay private.

If any Sonos units can run S1, you could keep everything LAN-only — worth
checking per device, but not required given current setup.

-----

## 7. Development trajectory (build order = feedback order)

Each phase is independently testable. Do not start a phase until the previous
one is green.

> **Build status (code phases done; hardware phases pending).** Phases 0, 1, 2,
> and the code-able parts of Phase 5 are implemented, unit-tested (ruff + mypy
> --strict + pytest green), and on PR #2. What remains is human/hardware: the
> Amperfy listening/browse test (Phase 1/2 exit), then bonob + Sonos (Phases
> 3–4). An opt-in live harness (`pytest -m integration`) produces the audio
> evidence for the Amperfy step.

### Phase 0 — Scaffolding ✅ done

- Stand up the shim as a sibling FastAPI service in the Hum repo (stack
  decision resolved, §2), with `/rest/ping` returning a valid
  `subsonic-response` JSON envelope.
- **Exit test:** `curl` ping returns the correct envelope. ✅

### Phase 1 — Auth + search + stream (minimum playable) ✅ code done

- Implement `ping`, `getLicense`, `search3`, `stream`, `getCoverArt`.
- Implement Subsonic token auth (`t`+`s` salted-MD5; plaintext `p` fallback
  for dev) — bonob sends token auth by default (§9).
- Implement the ID scheme (`vid:`/`pl:`/`art:`) with Hum's ID validation rules.
- Implement live-hit filtering in `search3` (§3.4).
- Implement the shim details cache (§5).
- Implement `stream` as **AAC remux (Mode 1)** with mp3 re-encode (Mode 2)
  fallback, range-ignoring first.
- **Exit test:** point **Amperfy** at the shim. Search a track, play it, hear
  audio. Verify both an AAC-remuxed and a forced-mp3 stream play. This
  validates the hardest parts with a trusted client. **Do not proceed to Sonos
  until Amperfy plays cleanly.** ⏳ awaiting human test.

### Phase 2 — Browsing ✅ code done

- Implement `getMusicFolders`, `getArtists`/`getIndexes`, `getPlaylists`,
  `getPlaylist`, `getAlbumList2` (empty `recent`/`frequent`). ✅
- Build the synthetic hierarchy (Search / Playlists). ✅ Playlist hits surface
  as drill-in albums (`getAlbum`/`getPlaylist` on `pl:` ids); artist/album
  catalog is intentionally empty (discovery via search).
- **Exit test:** Amperfy shows browsable structure; playlists load and play.
  ⏳ awaiting human test.

**Sonos/bonob note (verified against bonob source).** bonob is a browse bridge,
not a library-syncing client: it fetches from the shim on demand and Sonos keeps
no persistent catalog, so `search3` results are **not** accumulated into a
library (the DB-pollution seen in Amperfy does not occur on Sonos). bonob's
top-level containers map to `getArtists`/`getAlbumList2`/`getGenres` (empty
here — no catalog), `getStarred2` (Favourites ✅), `getPlaylists`, **Internet
Radio** (`getInternetRadioStations`), and Search. The populated, non-polluting
Sonos surfaces are therefore:
- **Playlists** ✅ — `getPlaylists` returns `SHIM_PINNED_PLAYLISTS` + starred
  `pl:` playlists (Hum can't enumerate; curated only).
- **Internet Radio** ✅ (listing) — `getInternetRadioStations` maps Hum
  `/api/radio` live streams to stations; `streamUrl` → the shim's
  unauthenticated `/radio/{id}` mp3 pipe (needs `SHIM_PUBLIC_URL`).
  ⚠️ **live-stream → Sonos-radio playback is unverified** (hardware gate).
- **Favourites** ✅ — `getStarred2`.

### Phase 3 — bonob (LAN, S1-style first if possible)

- Run bonob (Docker, pinned tag) pointed at the shim via `BNB_SUBSONIC_URL`.
- If any S1-capable device: register locally, validate end to end on LAN.
- **Exit test:** Hum appears as a source in the Sonos app; search + play works.

### Phase 4 — S2 / internet exposure (if required)

- Put bonob behind HTTPS reverse proxy with public DNS.
- Lock down firewall; keep shim + Hum private.
- Re-register service for S2; confirm Sonos cloud reaches bonob.
- **Exit test:** play from Sonos app on S2 hardware.

### Phase 5 — Polish (code-able parts ✅ done)

- ✅ scrobble (accepts/no-ops; Hum has no history to write).
- ✅ favourites — `star`/`unstar`/`getStarred2` over a shim-side JSON store
  (`SHIM_DATA_DIR`), titles rendered from a recently-emitted cache (no
  extraction).
- ✅ cover-art sizing — `size` selects an `i.ytimg` variant (no decode/dep).
- ✅ richer error envelopes — Hum 4xx (unplayable/region/live) → Subsonic 70,
  5xx/transport (Hum down) → 0, instead of bare 500s.
- ✅ ffmpeg lifecycle hardening — stderr logged on real failure; disconnect vs
  failure distinguished via GeneratorExit/cancel, not returncode.
- ✅ transcode mode (b) seeking — `SHIM_SEEKABLE_REMUX` materializes the remux
  to a cached `+faststart` file served with Range. **Off by default** (adds
  first-byte latency); flip on and validate during the Sonos phase.
- **Queue-ahead prefetch — investigated, not built.** The per-track Subsonic
  `stream` contract never exposes the next queue item to the shim, so there's
  nothing to prefetch from; speculative warming would trigger expensive
  extractions. The details cache (§5) remains the latency mitigation.
- Possible later phase: "Radio" browse entry backed by `/api/radio` if live
  HLS → Sonos-safe stream proves workable.

-----

## 8. Risk register

|Risk                                             |Likelihood|Impact|Mitigation                                                              |
|-------------------------------------------------|----------|------|------------------------------------------------------------------------|
|Remuxed AAC rejected by Sonos                    |Low-Med   |Med   |Validate with Amperfy first; ADTS variant second; mp3 256k re-encode fallback|
|Range requests break seeking                     |High      |Med   |Ship range-ignoring first; temp-file mode later                         |
|ffmpeg process leaks                             |Med       |Med   |Tie process lifecycle to request (`body_iterator` pattern); reap on disconnect|
|Cold-extraction first-byte latency (seconds)     |Med       |Med   |Shim details cache; queue-ahead prefetch; Hum single-flights extraction |
|pytubefix breaks (YouTube change)                |Med       |High  |Inherited from Hum; fix isolated to `app/adapters/youtube.py`           |
|Live hits leak into search results, fail playback|Med       |Med   |`_looks_live`-style filter in `search3`                                 |
|Subsonic↔library model mismatch confuses Sonos UI|Med       |Low   |Keep hierarchy minimal; lead with Search                                |
|S2 internet exposure surface                     |Accepted  |Med   |Only bonob public; firewall to Sonos IPs; TLS; private shim/Hum         |
|bonob version drift                              |Low       |Low   |Pin bonob image to a fixed `vX.Y.Z` tag                                 |

-----

## 9. Decisions

Resolved by the codebase audit:

1. ~~Shim language~~ → **Python/FastAPI** (matches Hum; reuses its streaming
   and config idioms).
2. ~~Shim location~~ → **sibling service in the Hum repo**.
3. ~~Transcode format~~ → **AAC remux first, mp3 256k re-encode fallback** (§4).
4. ~~History/Recently-played~~ → **Hum has none.** Omit at Phase 1/2; optional
   shim-side feature later (fed by `scrobble`).
5. ~~Auth model~~ → **shim implements Subsonic token auth.** bonob sends
   **salted-MD5 token auth** by default — `t` (MD5 hex of `password + s`) +
   `s` (random salt). The shim must implement the token-auth hash check
   (`MD5(password + salt)`). Plain `p` (password in clear/hex) is acceptable
   as a fallback for Amperfy dev mode only. Treating auth as fully optional
   means bonob's credential handshake will silently fail.

6. ~~Hierarchy scope~~ → **Search + Playlists.** search3 returns video songs +
   playlist albums; `getAlbum`/`getPlaylist` expand a playlist's items. The
   artist/album catalog (`getArtists`/`getAlbumList2`) is intentionally empty —
   a search-centric source has no static library.

-----

## 10. Reference endpoints (Hum, verified against code)

In scope for the shim:

|Hum endpoint                          |Use in shim                          |
|--------------------------------------|-------------------------------------|
|`GET /api/search?q=&limit=&category=` |`search3` (filter live hits)         |
|`GET /api/video/{id}`                 |signed audio/thumbnail URLs + metadata for `stream`/`getCoverArt`; **expensive — cache**|
|`GET /api/playlist/{id}`              |`getPlaylist`                        |
|`GET /api/channel/{id}`               |`getArtist` (optional)               |
|`GET /proxy/audio/{id}?itag&exp&sig`  |ffmpeg input for `stream` (range-aware)|
|`GET /proxy/thumbnail/{id}?itag=0&exp&sig`|`getCoverArt` (when details cached) |
|`GET /health`                         |shim → Hum liveness                  |

Exists in Hum but **out of scope** for the shim (live/radio/HLS surfaces):

|Hum endpoint                              |Why excluded                          |
|------------------------------------------|--------------------------------------|
|`GET /api/radio`                          |Live streams don't fit the Subsonic track model; possible Phase 5+|
|`GET /api/hls/{id}.m3u8`                  |Safari-specific byterange wrapper; Subsonic wants progressive streams|
|`GET /api/live/{id}/manifest.m3u8`        |Live HLS; out of scope                |
|`GET /proxy/live-segment/{id}`            |Live HLS; out of scope                |

All Hum `/api/*` calls require `Authorization: Bearer <token>`; the shim holds
that token server-side and never exposes it to bonob/Sonos.
