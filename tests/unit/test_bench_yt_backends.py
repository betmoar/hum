"""Offline logic of scripts/bench_yt_backends.py (stats, D1–D5, report, scrub).
The network parts only run on a machine that can reach YouTube."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "bench_yt_backends.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_yt_backends", _PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # dataclasses resolve annotations via sys.modules[cls.__module__].
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


bench = _load()


def _v(
    backend: str,
    secs: float,
    *,
    ok: bool = True,
    expect: str = "vod",
    itags: tuple[int, ...] = (140,),
    live_url: bool = False,
) -> object:
    return bench.VideoResult(
        backend=backend,
        item_id="x",
        label="l",
        expect=expect,
        seconds=secs,
        ok=ok,
        error=None if ok else "UPSTREAM_FAILURE",
        audio_itags=list(itags),
        has_live_url=live_url,
        playable=ok,
        title="t",
    )


def _s(backend: str, secs: float, *, titled: float = 1.0) -> object:
    return bench.SearchResult(
        backend=backend,
        query="q",
        seconds=secs,
        ok=True,
        error=None,
        hits=10,
        titled_fraction=titled,
    )


def test_percentiles_nearest_rank() -> None:
    assert bench.percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0
    assert bench.percentile([1.0, 2.0, 3.0, 4.0], 95) == 4.0
    assert bench.percentile([5.0], 95) == 5.0


def test_criteria_all_pass() -> None:
    videos = [_v("pytubefix", 1.0), _v("pytubefix", 1.2), _v("ytdlp", 1.5), _v("ytdlp", 1.8)]
    searches = [_s("pytubefix", 1.0), _s("ytdlp", 1.1)]
    verdict = bench.evaluate(videos, searches)
    assert all(verdict[k]["pass"] for k in ("D1", "D2", "D3", "D4", "D5")), verdict


def test_d1_fails_when_twice_as_slow() -> None:
    verdict = bench.evaluate(
        [_v("pytubefix", 1.0), _v("ytdlp", 2.2)], [_s("pytubefix", 1.0), _s("ytdlp", 1.0)]
    )
    assert verdict["D1"]["pass"] is False


def test_d1_fails_on_absolute_ceiling() -> None:
    verdict = bench.evaluate(
        [_v("pytubefix", 2.0), _v("ytdlp", 2.6)], [_s("pytubefix", 1.0), _s("ytdlp", 1.0)]
    )
    assert verdict["D1"]["pass"] is False


def test_d4_counts_unexpected_outcomes() -> None:
    videos = [
        _v("pytubefix", 1.0),
        _v("ytdlp", 1.0, ok=False),
        # An expected error is not a failure for either backend.
        _v("pytubefix", 1.0, ok=False, expect="error"),
        _v("ytdlp", 1.0, ok=False, expect="error"),
    ]
    verdict = bench.evaluate(videos, [_s("pytubefix", 1.0), _s("ytdlp", 1.0)])
    assert verdict["D4"]["pass"] is False
    assert verdict["D4"]["ytdlp_failures"] == 1 and verdict["D4"]["pytubefix_failures"] == 0


def test_d5_requires_140_or_251_and_live_manifest() -> None:
    verdict = bench.evaluate(
        [_v("pytubefix", 1.0), _v("ytdlp", 1.0, itags=(249,))],
        [_s("pytubefix", 1.0), _s("ytdlp", 1.0)],
    )
    assert verdict["D5"]["pass"] is False
    verdict = bench.evaluate(
        [_v("ytdlp", 1.0, expect="live", itags=(), live_url=False), _v("pytubefix", 1.0)],
        [_s("pytubefix", 1.0), _s("ytdlp", 1.0)],
    )
    assert verdict["D5"]["pass"] is False


def test_report_contains_verdict_and_tables() -> None:
    videos = [_v("pytubefix", 1.0), _v("ytdlp", 1.5)]
    searches = [_s("pytubefix", 1.0, titled=0.0), _s("ytdlp", 1.1)]
    md = bench.render_report(
        videos, searches, bench.evaluate(videos, searches), meta={"yt_dlp": "x"}
    )
    for needle in ("| D1 |", "| D5 |", "pytubefix", "ytdlp", "Titled hits", "D6"):
        assert needle in md


def test_scrub_removes_signed_urls_and_extra_keys() -> None:
    info = {
        "id": "abc",
        "title": "T",
        "channel": "C",
        "channel_id": "UC",
        "duration": 10,
        "view_count": 1,
        "live_status": "not_live",
        "description": "d" * 1000,
        "http_headers": {"User-Agent": "x"},
        "subtitles": {"en": []},
        "formats": [
            {
                "format_id": "140",
                "ext": "m4a",
                "protocol": "https",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "abr": 129.5,
                "url": "https://rr3---sn-abc.googlevideo.com/videoplayback?expire=1790000000&ip=203.0.113.9&sig=SECRET&itag=140",
                "http_headers": {"Cookie": "SECRET"},
            }
        ],
    }
    out = bench.scrub_video_info(info)
    blob = json.dumps(out)
    assert "203.0.113.9" not in blob and "SECRET" not in blob and "http_headers" not in blob
    assert "subtitles" not in out and len(out["description"]) <= 200
    f = out["formats"][0]
    assert "itag=140" in f["url"] and "expire=1790000000" in f["url"]


def test_scrub_search_keeps_mapping_fields() -> None:
    info = {
        "entries": [
            {
                "_type": "url",
                "ie_key": "Youtube",
                "id": "v",
                "title": "T",
                "channel": "C",
                "duration": 3.0,
                "url": "https://www.youtube.com/watch?v=v",
                "thumbnails": [{"url": "a"}, {"url": "b"}],
                "view_count": 5,
                "description": "x",
            }
        ]
    }
    e = bench.scrub_search_info(info)["entries"][0]
    assert e["thumbnails"] == [{"url": "b"}] and "view_count" not in e and e["title"] == "T"


def test_load_set_file_shape() -> None:
    data = bench.load_set(Path(__file__).resolve().parents[2] / "scripts" / "bench_yt_set.json")
    kinds = [v["expect"] for v in data["videos"]]
    assert kinds.count("vod") >= 13 and kinds.count("live") == 2 and kinds.count("error") == 2
    assert len(data["queries"]) == 6


@pytest.mark.parametrize("bad", [{"videos": []}, {"videos": [{"id": "x"}], "queries": []}])
def test_load_set_rejects_malformed(tmp_path: Path, bad: dict[str, object]) -> None:
    p = tmp_path / "s.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        bench.load_set(p)


def test_report_blames_environment_when_everything_failed() -> None:
    videos = [_v("pytubefix", 1.0, ok=False), _v("ytdlp", 1.0, ok=False)]
    md = bench.render_report(videos, [], bench.evaluate(videos, []), meta={})
    assert "Every item failed" in md and "Set-file problems" not in md
