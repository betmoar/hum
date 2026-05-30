"""GET /proxy/stream/{id} — signed video stream proxy (mirror of audio.py)."""
from __future__ import annotations

from app.proxy._common import create_signed_stream_router

router = create_signed_stream_router("/proxy", "/stream/{video_id}", "/proxy/stream")
