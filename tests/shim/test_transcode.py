"""Unit tests for format selection, ffmpeg args, and pipe lifecycle."""
from __future__ import annotations

import asyncio
import logging

import pytest

from shim import transcode
from shim.models import HumAudioFormat
from shim.subsonic import SubsonicError
from shim.transcode import ffmpeg_args, media_type_for, pick_audio_format, stream_ffmpeg


def _fmt(codec: str, bitrate: int, itag: int = 1) -> HumAudioFormat:
    return HumAudioFormat(
        itag=itag, mime_type=f"audio/{codec}", bitrate=bitrate, codec=codec, url="/x"
    )


def test_prefers_aac_even_at_lower_bitrate() -> None:
    fmt, mode = pick_audio_format([_fmt("opus", 160000), _fmt("aac", 128000)])
    assert fmt.codec == "aac"
    assert mode == "remux"


def test_picks_highest_bitrate_aac() -> None:
    fmt, _ = pick_audio_format([_fmt("aac", 48000, itag=139), _fmt("aac", 128000, itag=140)])
    assert fmt.itag == 140


def test_falls_back_to_mp3_without_aac() -> None:
    fmt, mode = pick_audio_format([_fmt("opus", 70000), _fmt("opus", 160000)])
    assert fmt.bitrate == 160000
    assert mode == "mp3"


def test_no_formats_raises() -> None:
    with pytest.raises(SubsonicError):
        pick_audio_format([])


def test_remux_args_are_copy_to_fmp4() -> None:
    args = ffmpeg_args("http://x/a", "remux", ffmpeg_path="ffmpeg", mp3_bitrate_kbps=256)
    assert args[0] == "ffmpeg"
    assert ["-c:a", "copy"] == args[args.index("-c:a") : args.index("-c:a") + 2]
    assert ["-f", "mp4"] == args[args.index("-f") : args.index("-f") + 2]
    assert "frag_keyframe+empty_moov" in args
    assert args[-1] == "-"


def test_mp3_args_re_encode() -> None:
    args = ffmpeg_args("http://x/a", "mp3", ffmpeg_path="ffmpeg", mp3_bitrate_kbps=256)
    assert "libmp3lame" in args
    assert "256k" in args
    assert args[-1] == "-"


def test_media_types() -> None:
    assert media_type_for("remux") == "audio/mp4"
    assert media_type_for("mp3") == "audio/mpeg"


# ----- ffmpeg pipe lifecycle (spec §4 hardening) ----------------------------


class _FakeReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, n: int = -1) -> bytes:
        if n == -1:  # stderr drain: return everything at once
            data = b"".join(self._chunks)
            self._chunks = []
            return data
        return self._chunks.pop(0) if self._chunks else b""


class _FakeProc:
    def __init__(
        self,
        stdout: list[bytes],
        returncode: int,
        stderr: bytes = b"",
        running: bool = False,
    ) -> None:
        self.stdout = _FakeReader(stdout)
        self.stderr = _FakeReader([stderr] if stderr else [])
        self._final = returncode
        self._running = running  # still executing when reaped (disconnect case)
        self.returncode: int | None = None
        self.killed = False

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        # Killing a still-running process yields -9 (SIGKILL); killing an
        # already-exited one is a no-op and wait() returns its real code.
        self.returncode = -9 if (self._running and self.killed) else self._final
        return self.returncode


def _patch_proc(monkeypatch: pytest.MonkeyPatch, proc: _FakeProc) -> None:
    async def fake_exec(*args: object, **kwargs: object) -> _FakeProc:
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)


async def test_stream_yields_all_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_proc(monkeypatch, _FakeProc([b"frag1", b"frag2"], returncode=0))
    out = b"".join([chunk async for chunk in stream_ffmpeg(["ffmpeg"])])
    assert out == b"frag1frag2"


async def test_nonzero_exit_logs_stderr(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_proc(monkeypatch, _FakeProc([], returncode=1, stderr=b"boom: bad input"))
    with caplog.at_level(logging.WARNING, logger="shim.transcode"):
        out = b"".join([chunk async for chunk in stream_ffmpeg(["ffmpeg"])])
    assert out == b""
    messages = [r.getMessage() for r in caplog.records]
    assert any("boom: bad input" in m and "1" in m for m in messages)


async def test_client_disconnect_kills_without_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    proc = _FakeProc([b"a", b"b", b"c"], returncode=1, running=True)
    _patch_proc(monkeypatch, proc)
    agen = stream_ffmpeg(["ffmpeg"])
    first = await agen.__anext__()
    assert first == b"a"
    with caplog.at_level(logging.WARNING, logger="shim.transcode"):
        await agen.aclose()  # client went away
    assert proc.killed is True
    # Killed-by-us is not a transcode failure, so no warning is emitted.
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
