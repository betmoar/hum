Scrubbed real yt-dlp `extract_info` responses used by `tests/unit/test_youtube_adapter.py`.

Re-capture where YouTube is reachable (needs deno):
`uv run python scripts/capture_ytdlp_fixtures.py`. Signed, IP-bound CDN URLs are
replaced by placeholders, so the files are safe to commit.
