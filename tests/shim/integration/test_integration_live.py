"""Live end-to-end checks: search returns songs, and a stream decodes as audio.

Opt-in (`-m integration`); skips unless a running shim is reachable. Produces
the same evidence a human would check before the Amperfy test.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration

_MAX_STREAM_BYTES = 512 * 1024  # enough for ffprobe to identify the codec


def _first_song_id(base: str, auth: dict[str, str], query: str) -> str:
    r = httpx.get(f"{base}/rest/search3", params={**auth, "query": query}, timeout=30.0)
    r.raise_for_status()
    body = r.json()["subsonic-response"]
    assert body["status"] == "ok", body
    songs = body.get("searchResult3", {}).get("song", [])
    if not songs:
        pytest.skip(f"no songs returned for {query!r}")
    return str(songs[0]["id"])


def test_search3_returns_songs(shim_base: str, shim_auth: dict[str, str]) -> None:
    sid = _first_song_id(shim_base, shim_auth, "lofi hip hop")
    assert sid.startswith("vid:")


def test_stream_decodes_as_audio(
    shim_base: str, shim_auth: dict[str, str], ffprobe: str
) -> None:
    sid = _first_song_id(shim_base, shim_auth, "lofi hip hop")

    collected = bytearray()
    with httpx.stream(
        "GET", f"{shim_base}/rest/stream", params={**shim_auth, "id": sid}, timeout=60.0
    ) as r:
        r.raise_for_status()
        assert r.headers["content-type"] in ("audio/mp4", "audio/mpeg")
        for chunk in r.iter_bytes():
            collected.extend(chunk)
            if len(collected) >= _MAX_STREAM_BYTES:
                break
    assert collected, "stream produced no bytes"

    with tempfile.NamedTemporaryFile(suffix=".bin") as f:
        Path(f.name).write_bytes(bytes(collected))
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "json", f.name],
            capture_output=True, text=True, timeout=30,
        )
    streams = json.loads(out.stdout or "{}").get("streams", [])
    codec_types = {s.get("codec_type") for s in streams}
    assert "audio" in codec_types, f"ffprobe found no audio stream: {out.stdout} {out.stderr}"
