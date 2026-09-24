#!/usr/bin/env python3
"""Benchmark the pytubefix and yt-dlp backends against real YouTube.

Spike tool for spike/ytdlp-backend (docs/dev/2026-09-24-ytdlp-spike-spec.md).
Needs network access to YouTube and, for the yt-dlp backend, deno on PATH.
Never run in CI.

    uv run python scripts/bench_yt_backends.py              # writes the report
    uv run python scripts/bench_yt_backends.py --capture    # also saves fixtures

For each backend: clear the adapter caches, run every video and query cold,
then every video once warm (cache hit). A VOD counts as "playable" only if
its first audio format's upstream URL returns bytes through Hum's own
upstream client — the same path /proxy/audio uses.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import os
import platform
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SET = ROOT / "scripts" / "bench_yt_set.json"
DEFAULT_REPORT = ROOT / "docs" / "dev" / "ytdlp-spike-report.md"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "ytdlp"
BACKENDS = ("pytubefix", "ytdlp")

# Decision thresholds, fixed in the approved spec (D1–D5). Do not tune these
# after seeing results.
D1_ABS_P50_S = 2.5
D1_REL_P50 = 2.0
D2_ABS_P95_S = 5.0
D3_REL_SEARCH_P50 = 1.3


@dataclass
class VideoResult:
    backend: str
    item_id: str
    label: str
    expect: str  # "vod" | "live" | "error"
    seconds: float
    ok: bool
    error: str | None
    audio_itags: list[int]
    has_live_url: bool
    playable: bool
    title: str


@dataclass
class SearchResult:
    backend: str
    query: str
    seconds: float
    ok: bool
    error: str | None
    hits: int
    titled_fraction: float  # hits with a non-empty title AND author (issue #14)


# ---- pure helpers (unit-tested) -------------------------------------------


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; values must be non-empty."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def load_set(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    videos, queries = data.get("videos"), data.get("queries")
    if not videos or not queries:
        raise ValueError(f"{path}: needs non-empty 'videos' and 'queries'")
    for v in videos:
        if not isinstance(v.get("id"), str) or v.get("expect") not in ("vod", "live", "error"):
            raise ValueError(f"{path}: bad video entry {v!r}")
    return dict(data)


def _unexpected(r: VideoResult) -> bool:
    """True when the outcome doesn't match the item's expectation."""
    if r.expect == "error":
        return r.ok  # an error item that "succeeds" is suspicious too
    if not r.ok:
        return True
    if r.expect == "live":
        return not r.has_live_url
    return not r.playable


def _p(values: list[float], pct: float) -> float | None:
    return percentile(values, pct) if values else None


def evaluate(videos: list[VideoResult], searches: list[SearchResult]) -> dict[str, dict[str, Any]]:
    def vod_times(b: str) -> list[float]:
        return [r.seconds for r in videos if r.backend == b and r.expect == "vod" and r.ok]

    def search_times(b: str) -> list[float]:
        return [r.seconds for r in searches if r.backend == b and r.ok]

    pt50, yd50 = _p(vod_times("pytubefix"), 50), _p(vod_times("ytdlp"), 50)
    yd95 = _p(vod_times("ytdlp"), 95)
    ps50, ys50 = _p(search_times("pytubefix"), 50), _p(search_times("ytdlp"), 50)
    pf = sum(1 for r in videos if r.backend == "pytubefix" and _unexpected(r))
    yf = sum(1 for r in videos if r.backend == "ytdlp" and _unexpected(r))
    yd_vod_ok = [r for r in videos if r.backend == "ytdlp" and r.expect == "vod" and r.ok]
    yd_live = [r for r in videos if r.backend == "ytdlp" and r.expect == "live" and r.ok]

    d1 = (
        yd50 is not None and pt50 is not None and yd50 <= D1_ABS_P50_S and yd50 <= D1_REL_P50 * pt50
    )
    d5 = (
        bool(yd_vod_ok)
        and all({140, 251} & set(r.audio_itags) for r in yd_vod_ok)
        and all(r.has_live_url for r in yd_live)
    )
    live_expected = [r for r in videos if r.backend == "ytdlp" and r.expect == "live"]
    if live_expected and not yd_live:
        d5 = False
    return {
        "D1": {"pass": d1, "pytubefix_p50": pt50, "ytdlp_p50": yd50},
        "D2": {"pass": yd95 is not None and yd95 <= D2_ABS_P95_S, "ytdlp_p95": yd95},
        "D3": {
            "pass": ys50 is not None and ps50 is not None and ys50 <= D3_REL_SEARCH_P50 * ps50,
            "pytubefix_p50": ps50,
            "ytdlp_p50": ys50,
        },
        "D4": {"pass": yf <= pf, "pytubefix_failures": pf, "ytdlp_failures": yf},
        "D5": {"pass": d5},
    }


def _fmt_s(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f} s"


def render_report(
    videos: list[VideoResult],
    searches: list[SearchResult],
    verdict: dict[str, dict[str, Any]],
    *,
    meta: dict[str, str],
) -> str:
    out = ["# yt-dlp spike report", ""]
    out += [f"- {k}: `{v}`" for k, v in meta.items()]
    out += [
        "",
        "## Decision criteria (fixed in the spec before measuring)",
        "",
        "| # | Criterion | Result | Pass |",
        "|---|---|---|---|",
    ]
    d = verdict
    out.append(
        f"| D1 | cold video p50 ≤ {D1_ABS_P50_S} s and ≤ {D1_REL_P50}× pytubefix | "
        f"ytdlp {_fmt_s(d['D1']['ytdlp_p50'])} vs pytubefix {_fmt_s(d['D1']['pytubefix_p50'])} | "
        f"{'✅' if d['D1']['pass'] else '❌'} |"
    )
    out.append(
        f"| D2 | cold video p95 ≤ {D2_ABS_P95_S} s | ytdlp {_fmt_s(d['D2']['ytdlp_p95'])} | "
        f"{'✅' if d['D2']['pass'] else '❌'} |"
    )
    out.append(
        f"| D3 | search p50 ≤ {D3_REL_SEARCH_P50}× pytubefix | "
        f"ytdlp {_fmt_s(d['D3']['ytdlp_p50'])} vs pytubefix {_fmt_s(d['D3']['pytubefix_p50'])} | "
        f"{'✅' if d['D3']['pass'] else '❌'} |"
    )
    out.append(
        f"| D4 | unexpected outcomes ≤ pytubefix | ytdlp {d['D4']['ytdlp_failures']} vs "
        f"pytubefix {d['D4']['pytubefix_failures']} | {'✅' if d['D4']['pass'] else '❌'} |"
    )
    out.append(
        f"| D5 | itag 140/251 on every playable VOD; live has manifest | — | "
        f"{'✅' if d['D5']['pass'] else '❌'} |"
    )
    out += [
        "",
        "D6 (loudness): yt-dlp does not expose `loudnessDb`; recoverability is a manual note.",
        "",
    ]

    out += ["## Videos (cold)", "", "| Item | Expect | pytubefix | ytdlp |", "|---|---|---|---|"]
    by_item: dict[str, dict[str, VideoResult]] = {}
    for r in videos:
        by_item.setdefault(r.item_id, {})[r.backend] = r
    both_failed: list[str] = []

    def cell(r: VideoResult | None) -> str:
        if r is None:
            return "—"
        status = "ok" if r.ok else (r.error or "error")
        extra = "" if r.expect != "vod" or not r.ok else (" ▶" if r.playable else " ✖play")
        return f"{r.seconds:.2f} s {status}{extra}"

    for item_id, pair in by_item.items():
        any_r = next(iter(pair.values()))
        out.append(
            f"| {any_r.label} (`{item_id}`) | {any_r.expect} | {cell(pair.get('pytubefix'))} | "
            f"{cell(pair.get('ytdlp'))} |"
        )
        if any_r.expect != "error" and all(not r.ok for r in pair.values()):
            both_failed.append(item_id)

    out += [
        "",
        "## Searches (cold)",
        "",
        "| Query | pytubefix | ytdlp | Titled hits (pytubefix / ytdlp) |",
        "|---|---|---|---|",
    ]
    by_q: dict[str, dict[str, SearchResult]] = {}
    for s in searches:
        by_q.setdefault(s.query, {})[s.backend] = s

    def scell(s: SearchResult | None) -> str:
        if s is None:
            return "—"
        return f"{s.seconds:.2f} s, {s.hits} hits" if s.ok else f"{s.seconds:.2f} s {s.error}"

    for q, pair in by_q.items():
        p, y = pair.get("pytubefix"), pair.get("ytdlp")
        tf = " / ".join(f"{x.titled_fraction:.0%}" if x else "—" for x in (p, y))
        out.append(f"| {q} | {scell(p)} | {scell(y)} | {tf} |")

    all_items = [i for i, pair in by_item.items() if next(iter(pair.values())).expect != "error"]
    if all_items and len(both_failed) == len(all_items):
        out += [
            "",
            "## Every item failed on both backends",
            "",
            "That is an environment problem, not the set file: check network access to "
            "YouTube and that deno is on PATH, then re-run.",
        ]
    elif both_failed:
        out += [
            "",
            "## Set-file problems",
            "",
            "Failed on both backends — likely a dead id, replace and re-run: "
            + ", ".join(f"`{i}`" for i in both_failed),
        ]
    return "\n".join(out) + "\n"


_GV_URL = re.compile(r"https?://[^\"'\s]*googlevideo\.com[^\"'\s]*")
_VIDEO_KEYS = (
    "id",
    "title",
    "channel",
    "uploader",
    "channel_id",
    "duration",
    "view_count",
    "live_status",
    "description",
)
_FORMAT_KEYS = (
    "format_id",
    "ext",
    "protocol",
    "vcodec",
    "acodec",
    "abr",
    "tbr",
    "asr",
    "audio_channels",
    "width",
    "height",
    "fps",
    "url",
    "manifest_url",
)
_ENTRY_KEYS = (
    "_type",
    "ie_key",
    "id",
    "title",
    "channel",
    "uploader",
    "duration",
    "live_status",
    "url",
    "thumbnails",
    "playlist_count",
)


def _scrub_url(url: str, format_id: str) -> str:
    """Replace a signed, IP-bound CDN URL with a placeholder keeping only
    itag + expire (what the adapter reads). Captured fixtures get committed."""
    m = re.search(r"[?&]expire=(\d+)", url)
    expire = m.group(1) if m else "0"
    return f"https://rr1---sn.googlevideo.com/videoplayback?itag={format_id}&expire={expire}"


def scrub_video_info(info: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: info[k] for k in _VIDEO_KEYS if k in info}
    if isinstance(out.get("description"), str):
        out["description"] = out["description"][:200]
    formats = []
    for f in info.get("formats") or []:
        g = {k: f[k] for k in _FORMAT_KEYS if k in f}
        fid = str(g.get("format_id", ""))
        for key in ("url", "manifest_url"):
            if isinstance(g.get(key), str) and "googlevideo.com" in g[key]:
                g[key] = _scrub_url(g[key], fid)
        formats.append(g)
    out["formats"] = formats
    for leftover in _GV_URL.findall(json.dumps(out)):
        if re.search(r"[?&](ip|sig|lsig|signature|n)=", leftover):
            raise ValueError("scrub left a signed URL behind")
    return out


def scrub_search_info(info: dict[str, Any]) -> dict[str, Any]:
    entries = []
    for e in info.get("entries") or []:
        if not isinstance(e, dict):
            continue
        g = {k: e[k] for k in _ENTRY_KEYS if k in e}
        if isinstance(g.get("thumbnails"), list) and g["thumbnails"]:
            g["thumbnails"] = [g["thumbnails"][-1]]
        entries.append(g)
    return {"_type": info.get("_type", "playlist"), "entries": entries}


# ---- network runner --------------------------------------------------------


def _err(e: BaseException) -> str:
    """A mapped YouTubeError reports its code; anything else escaped the
    adapter unmapped (would be a bare 500 in the app) and is labelled so."""
    code = getattr(e, "code", None)
    return code if isinstance(code, str) else f"UNMAPPED:{type(e).__name__}"


def _clear_caches() -> None:
    from app.adapters import youtube

    for cache in (
        youtube._stream_url_cache,
        youtube._video_details_cache,
        youtube._search_cache,
        youtube._inflight_refresh,
        youtube._inflight_video,
        youtube._inflight_search,
    ):
        cache.clear()


async def _run_video(backend: str, item: dict[str, Any]) -> VideoResult:
    from app.adapters import upstream_http, youtube

    t0 = time.perf_counter()
    try:
        d = await youtube.video(item["id"])
    except Exception as e:  # noqa: BLE001 — record, don't crash the run
        return VideoResult(
            backend,
            item["id"],
            item["label"],
            item["expect"],
            time.perf_counter() - t0,
            False,
            _err(e),
            [],
            False,
            False,
            "",
        )
    secs = time.perf_counter() - t0
    playable = False
    if d.audio_formats:
        try:
            url = await youtube.resolve_upstream_url(item["id"], d.audio_formats[0].itag)
            playable = len(await upstream_http.fetch_range(url, start=0, end=1023)) > 0
        except Exception:
            playable = False
    return VideoResult(
        backend,
        item["id"],
        item["label"],
        item["expect"],
        secs,
        True,
        None,
        [a.itag for a in d.audio_formats],
        bool(d.is_live and d.live_stream_url),
        playable,
        d.title,
    )


async def _run_search(backend: str, q: dict[str, Any]) -> SearchResult:
    from app.adapters import youtube

    t0 = time.perf_counter()
    try:
        hits = await youtube.search(
            q["q"], 20, category=q.get("category"), live=bool(q.get("live"))
        )
    except Exception as e:  # noqa: BLE001 — record, don't crash the run
        return SearchResult(backend, q["q"], time.perf_counter() - t0, False, _err(e), 0, 0.0)
    secs = time.perf_counter() - t0
    titled = sum(1 for h in hits if h.title and h.author and h.author != "unknown")
    return SearchResult(
        backend, q["q"], secs, True, None, len(hits), titled / len(hits) if hits else 0.0
    )


def _capture(set_data: dict[str, Any]) -> None:
    from app.adapters import youtube_ytdlp

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    first = {v["expect"]: v["id"] for v in reversed(set_data["videos"])}
    for kind, name in (("vod", "video_vod.json"), ("live", "video_live.json")):
        if kind in first:
            info = youtube_ytdlp._extract(f"https://www.youtube.com/watch?v={first[kind]}", {})
            (FIXTURE_DIR / name).write_text(json.dumps(scrub_video_info(info), indent=1))
    q = set_data["queries"][0]["q"]
    info = youtube_ytdlp._extract(
        "https://www.youtube.com/results?search_query=" + q.replace(" ", "+"),
        {"extract_flat": "in_playlist", "playlistend": 20},
    )
    (FIXTURE_DIR / "search_flat.json").write_text(json.dumps(scrub_search_info(info), indent=1))
    print(f"captured scrubbed fixtures into {FIXTURE_DIR}")


async def _main(args: argparse.Namespace) -> int:
    os.environ.setdefault("API_BEARER_TOKEN", "bench-token-not-used-0000")
    os.environ.setdefault("STREAM_SIGNING_KEY", "00" * 32)
    sys.path.insert(0, str(ROOT))
    from app.adapters import upstream_http, youtube
    from app.config import get_settings

    set_data = load_set(Path(args.set))
    settings = get_settings()
    videos: list[VideoResult] = []
    searches: list[SearchResult] = []
    try:
        for backend in BACKENDS:
            settings.yt_backend = backend  # type: ignore[assignment]
            _clear_caches()
            print(f"== {backend}: videos (cold)")
            for item in set_data["videos"]:
                r = await _run_video(backend, item)
                videos.append(r)
                print(f"  {item['id']} {r.seconds:.2f}s {'ok' if r.ok else r.error}")
            print(f"== {backend}: videos (warm)")
            for item in set_data["videos"]:
                t0 = time.perf_counter()
                with contextlib.suppress(Exception):
                    await youtube.video(item["id"])
                print(f"  {item['id']} {time.perf_counter() - t0:.3f}s")
            print(f"== {backend}: searches (cold)")
            for q in set_data["queries"]:
                s = await _run_search(backend, q)
                searches.append(s)
                print(f"  {q['q']!r} {s.seconds:.2f}s {s.hits} hits")
        if args.capture:
            _capture(set_data)
    finally:
        await upstream_http.close()

    import pytubefix
    import yt_dlp.version

    meta = {
        "date": time.strftime("%Y-%m-%d %H:%M %Z"),
        "platform": platform.platform(),
        "pytubefix": getattr(pytubefix, "__version__", "?"),
        "yt_dlp": yt_dlp.version.__version__,
        "deno": shutil.which("deno") or "NOT FOUND",
    }
    verdict = evaluate(videos, searches)
    Path(args.report).write_text(render_report(videos, searches, verdict, meta=meta))
    Path(args.report).with_suffix(".json").write_text(
        json.dumps(
            {
                "videos": [asdict(v) for v in videos],
                "searches": [asdict(s) for s in searches],
                "verdict": verdict,
                "meta": meta,
            },
            indent=1,
        )
    )
    print(f"report: {args.report}")
    return 0 if all(v["pass"] for v in verdict.values()) else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--set", default=str(DEFAULT_SET))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument(
        "--capture", action="store_true", help="save scrubbed yt-dlp fixtures for unit tests"
    )
    return asyncio.run(_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
