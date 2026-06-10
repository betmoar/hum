# Sonos shim — validation runbook (pick-up guide)

Everything code-able is done and on **PR #2** (branch `smapi`). What remains is
**human/hardware validation** — things a test suite can't do: listening by ear,
running bonob, and playing through a real Sonos speaker. Work top to bottom;
each step says what to expect and what to capture if it fails.

Status legend: ✅ done in code · 🎧 needs you (ear) · 📦 needs bonob · 🔊 needs Sonos hardware

---

## 0. Where things stand

- **Implemented + unit-tested (245 tests, green):** Subsonic `ping`, `getLicense`,
  `search3`, `stream` (AAC remux → mp3 fallback), `getCoverArt`, browsing
  (`getMusicFolders`/`getArtists`/`getIndexes`/`getAlbumList2`/`getPlaylists`/
  `getPlaylist`/`getAlbum`), favourites (`star`/`unstar`/`getStarred2`),
  `scrobble`, **Internet Radio** (`getInternetRadioStations` + `/radio/{id}`),
  XML+JSON responses, token + legacy auth.
- **Already validated this session:** Phase 0 ping; live integration suite
  (search3 + stream→ffprobe); Amperfy **login works** after the XML fix; search
  returns results; one track streamed end-to-end.
- **Not yet validated (this runbook):** Amperfy clean playback by ear; bonob;
  Sonos browse + playback; Internet Radio playback (the big unknown); seekable
  remux; S2 internet exposure.

---

## 1. One-time `.env` settings

Edit the repo-root `.env` (the shim and Hum share it):

```bash
# Required
SHIM_SUBSONIC_PASSWORD=<your password>        # what bonob/Amperfy log in with (>=8 chars)

# For Amperfy "legacy login" and curl poking (plain password). Turn OFF before any
# internet exposure (S2) — legacy sends the password in clear.
SHIM_ALLOW_PLAIN_PASSWORD=true

# For Internet Radio: the LAN address Sonos speakers can reach the shim at.
# Find your IP:  ipconfig getifaddr en0
SHIM_PUBLIC_URL=http://<imac-LAN-ip>:8001

# Optional: curated playlists for the Sonos Playlist shelf (comma-separated YT playlist IDs)
SHIM_PINNED_PLAYLISTS=

# Optional: gives Sonos a seek bar (adds first-byte latency). Validate separately.
SHIM_SEEKABLE_REMUX=false
```

`SHIM_HUM_BEARER_TOKEN` is **not** needed on the same box — it falls back to `API_BEARER_TOKEN`.

---

## 2. Start the stack (and the stale-process gotcha)

Always pull and **restart both** so the running processes have current code — a
stale shim caused several false failures this session.

```bash
cd /Volumes/Data/Workspace/dev/audio-tools/hum
git pull
uv sync --extra dev                 # refresh entry points after pulling

# stop any old shim still holding :8001
kill $(lsof -ti :8001) 2>/dev/null

hum &                               # Hum on :8000  (MUST be up — the shim proxies it)
hum-shim &                          # shim on :8001
```

Gotchas:
- If you see `address already in use` after "Application startup complete", a
  stale shim is on :8001 — `kill $(lsof -ti :8001)` and retry. (uvicorn logs the
  bind error *after* the startup line; misleading but harmless.)
- `hum shim` (space) is wrong and now errors — the shim is `hum-shim` (hyphen).
- Run from the repo root. Hum down → the shim returns clean "Hum unreachable"
  errors, but nothing will play.

---

## 3. Smoke test with curl (30 seconds, no client needed)

```bash
P=<your password>
# XML by default (what Amperfy/bonob get) — should be <subsonic-response status="ok">
curl -s "http://127.0.0.1:8001/rest/ping.view?u=hum&p=$P"
# JSON when asked
curl -s "http://127.0.0.1:8001/rest/ping.view?u=hum&p=$P&f=json"
# Root probe (Amperfy Auto-Detect needs this non-404)
curl -s "http://127.0.0.1:8001/"
# Search (slow: 6–60s, real pytubefix)
curl -s "http://127.0.0.1:8001/rest/search3?u=hum&p=$P&f=json&query=lofi"
# Radio shelf (needs Hum live search working)
curl -s "http://127.0.0.1:8001/rest/getInternetRadioStations?u=hum&p=$P&f=json"
```

Expect `status="ok"` envelopes; search returns `song` entries. If any return
`status="failed"`, the `error.message` says why (it surfaces Hum's error).

---

## 4. Integration suite (automated end-to-end, with the stack up)

```bash
pytest -m integration tests/shim/integration
```

Hits the running shim → Hum → YouTube, and ffprobes a stream as audio. Skips
cleanly if the shim or Hum is down. Green here = the server side is sound.

---

## 5. 🎧 Amperfy (Phase 1/2 exit) — confirms playback by ear

Amperfy is the trusted test client *before* Sonos. Note: Amperfy caches search
results into a local library (it's a syncing client) — that's an Amperfy trait,
**not** how Sonos behaves, so ignore the library "pollution" here.

1. Add server: URL `http://<imac-LAN-ip>:8001` (or `localhost` if same machine),
   user `hum`, your password.
2. **API mode: pick `Subsonic` or `Subsonic (legacy login)`** — not Ampache
   (wrong protocol), Auto-Detect now works too.
3. Search a track → it appears under **Songs**. Play it.

**Pass:** audio plays cleanly, no stutter/dropout. Try both an AAC track (most)
and confirm it sounds right. **This is the gate to proceed to Sonos.**

Capture if it fails: the shim's log lines for that play (the `/rest/stream` call)
and whether audio started at all.

---

## 6. 📦🔊 bonob + Sonos (Phase 3) — the real target

bonob bridges Sonos (SMAPI/SOAP) to the shim (Subsonic). Unlike Amperfy, Sonos
keeps **no persistent library** — it browses live, so search doesn't accumulate.

1. Run bonob (Docker, **pin a version tag**), pointed at the shim:
   ```
   BNB_SUBSONIC_URL=http://<imac-LAN-ip>:8001
   BNB_SECRET=<long random>
   BNB_URL=http://<imac-LAN-ip>:4534      # bonob's own LAN URL (S1/local)
   ```
2. Register bonob as a music service in the Sonos app (it prints setup steps).
3. In the Sonos app, open the Hum service and check each shelf:

| Shelf | Expect | Backed by |
|---|---|---|
| **Search** | finds + plays tracks | `search3` → `stream` |
| **Playlists** | your `SHIM_PINNED_PLAYLISTS` + starred playlists | `getPlaylists` |
| **Favourites** | tracks/playlists you starred | `getStarred2` |
| **Internet Radio** | live stations from Hum `/api/radio` | `getInternetRadioStations` |
| Artists/Albums/Genres | **empty** (no catalog — expected) | — |

**Pass:** Hum appears as a Sonos source; Search finds and **plays** a track on a
speaker. Capture if it fails: bonob's container logs + which shelf is empty/erroring.

---

## 7. 🔊 Internet Radio playback — the known unknown

Listing the stations is done; whether Sonos *plays* one is **unverified**. It
chains live YouTube → Hum HLS → ffmpeg mp3 → Sonos, and the last hop couldn't be
tested without hardware.

- Requires `SHIM_PUBLIC_URL` set to a LAN IP (not `127.0.0.1`) so the speaker can
  fetch `/radio/{id}` directly.
- Test: open **Internet Radio** in Sonos, pick a station, hit play.
- If it **doesn't** play: capture the shim log for the `/radio/<id>` request and
  run this to see if the pipe itself produces audio:
  ```bash
  curl -s "http://<imac-LAN-ip>:8001/radio/<a_live_video_id>" --max-time 10 -o /tmp/r.mp3
  ffprobe /tmp/r.mp3       # should show an mp3 audio stream
  ```
  That isolates "shim can't produce the stream" from "Sonos won't accept it."

---

## 8. Optional / later

- **Seekable remux (seek bar):** set `SHIM_SEEKABLE_REMUX=true`, restart, re-test
  a track in Sonos/Amperfy. Trades first-byte latency for a seek bar. Falls back
  to the streaming pipe if it fails.
- **S2 / internet exposure (Phase 4):** only if Sonos units are S2. Put **bonob
  only** behind HTTPS with a public DNS name; keep shim + Hum LAN-only. Set
  `SHIM_ALLOW_PLAIN_PASSWORD=false` and use token auth. (Spec §6.)

---

## 9. If you hand it back to Claude

For any failure, paste: (a) which step, (b) the shim log lines for the failing
request, (c) for bonob issues, the bonob container logs. The shim maps Hum errors
into the response `message`, so a `status="failed"` envelope usually names the
cause. Known perf note: search is slow (pytubefix, ~6–60s) and Amperfy fires one
search per keystroke — that's Hum-side latency, not a shim bug.
