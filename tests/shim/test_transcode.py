"""Unit tests for format selection and ffmpeg argument construction."""
from __future__ import annotations

import pytest

from shim.models import HumAudioFormat
from shim.subsonic import SubsonicError
from shim.transcode import ffmpeg_args, media_type_for, pick_audio_format


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
