"""ffmpeg pipe for /rest/stream (spec §4).

Mode 1 (default): AAC remux to fragmented MP4 — container fix only, near-zero
CPU, timing metadata preserved. Mode 2 (fallback): mp3 re-encode when a video
has no AAC format. Range requests are ignored for now (mode (a) in §4).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from shim.models import HumAudioFormat
from shim.subsonic import NOT_FOUND, SubsonicError

_CHUNK_BYTES = 64 * 1024
# How much stderr tail to keep for diagnostics on a non-zero exit.
_STDERR_TAIL_BYTES = 2048

_log = logging.getLogger("shim.transcode")

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


def remux_file_args(input_url: str, dest: Path, *, ffmpeg_path: str) -> list[str]:
    """Remux AAC to a complete .m4a file with the moov atom up front
    (+faststart) so it serves cleanly under Range requests — distinct from the
    fragmented, headerless container used for the streaming pipe."""
    return [
        ffmpeg_path, "-hide_banner", "-loglevel", "error",
        "-i", input_url, "-vn", "-c:a", "copy", "-movflags", "+faststart",
        str(dest),
    ]


async def materialize(args: list[str]) -> bool:
    """Run ffmpeg to completion writing to a file (args end in the dest path).
    Returns True on a clean exit; logs a stderr tail and returns False otherwise
    so the caller can fall back to the streaming pipe."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = (stderr or b"")[-_STDERR_TAIL_BYTES:].decode("utf-8", "replace").strip()
        _log.warning("ffmpeg materialize exited %s: %s", proc.returncode, tail or "<no stderr>")
        return False
    return True


async def stream_ffmpeg(args: list[str]) -> AsyncIterator[bytes]:
    """Yield ffmpeg stdout chunks, reaping the process on completion or client
    disconnect (the body_iterator pattern from app/proxy/_common.py applied to
    a subprocess — spec §4 process-lifecycle requirement).

    stderr is captured (ffmpeg runs at -loglevel error, so it's low-volume) and
    logged when ffmpeg exits non-zero for a reason other than our own kill, so a
    failed transcode leaves a diagnostic instead of a silently truncated stream.
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None  # guaranteed by stdout=PIPE
    disconnected = False
    try:
        while chunk := await proc.stdout.read(_CHUNK_BYTES):
            yield chunk
    except (BrokenPipeError, ConnectionResetError):
        disconnected = True
    except (GeneratorExit, asyncio.CancelledError):
        # Client went away (Starlette closes/cancels the body iterator).
        disconnected = True
        raise
    finally:
        # Reap. returncode is often still None here even when ffmpeg has already
        # exited (e.g. on failure), so we can't infer disconnect from it — kill
        # is harmless on an already-dead process, and wait() yields the real code.
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        stderr = b""
        if proc.stderr is not None:
            with contextlib.suppress(Exception):
                stderr = await proc.stderr.read()
        await proc.wait()
        # A non-zero exit we didn't cause by disconnecting = a real transcode
        # failure; leave a diagnostic instead of a silently truncated stream.
        if not disconnected and proc.returncode not in (0, None):
            tail = stderr[-_STDERR_TAIL_BYTES:].decode("utf-8", "replace").strip()
            _log.warning("ffmpeg exited %s: %s", proc.returncode, tail or "<no stderr>")
