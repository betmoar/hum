"""ffmpeg pipe for /rest/stream (spec §4).

Mode 1 (default): AAC remux to fragmented MP4 — container fix only, near-zero
CPU, timing metadata preserved. Mode 2 (fallback): mp3 re-encode when a video
has no AAC format. Range requests are ignored for now (mode (a) in §4).
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Literal

from shim.models import HumAudioFormat
from shim.subsonic import NOT_FOUND, SubsonicError

_CHUNK_BYTES = 64 * 1024

StreamMode = Literal["remux", "mp3"]


def pick_audio_format(formats: list[HumAudioFormat]) -> tuple[HumAudioFormat, StreamMode]:
    """Prefer the highest-bitrate AAC (remuxable); otherwise the
    highest-bitrate format of any codec, re-encoded to mp3."""
    if not formats:
        raise SubsonicError(NOT_FOUND, "no audio formats available")
    aac = [f for f in formats if f.codec == "aac"]
    if aac:
        return max(aac, key=lambda f: f.bitrate), "remux"
    return max(formats, key=lambda f: f.bitrate), "mp3"


def media_type_for(mode: StreamMode) -> str:
    return "audio/mp4" if mode == "remux" else "audio/mpeg"


def ffmpeg_args(
    input_url: str, mode: StreamMode, *, ffmpeg_path: str, mp3_bitrate_kbps: int
) -> list[str]:
    base = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-i", input_url, "-vn"]
    if mode == "remux":
        return [*base, "-c:a", "copy", "-f", "mp4", "-movflags", "frag_keyframe+empty_moov", "-"]
    return [*base, "-c:a", "libmp3lame", "-b:a", f"{mp3_bitrate_kbps}k", "-f", "mp3", "-"]


async def stream_ffmpeg(args: list[str]) -> AsyncIterator[bytes]:
    """Yield ffmpeg stdout chunks; the finally block reaps the process when
    the client disconnects (the body_iterator pattern from
    app/proxy/_common.py, applied to a subprocess instead of an httpx
    response — spec §4 process-lifecycle requirement)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdout is not None  # guaranteed by stdout=PIPE
    try:
        while chunk := await proc.stdout.read(_CHUNK_BYTES):
            yield chunk
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
