Hand-written yt-dlp `extract_info` shapes used by `tests/unit/test_youtube_ytdlp.py`.

UNVERIFIED against real YouTube until replaced by
`uv run python scripts/bench_yt_backends.py --capture` output (run where
YouTube is reachable). The capture writes `video_vod.json`, `video_live.json`
and `search_flat.json` here; the unit tests load them when present.
