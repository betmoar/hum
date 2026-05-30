"""GET /proxy/audio/{id} — signed, range-aware audio stream proxy."""
from __future__ import annotations

from app.proxy._common import create_signed_stream_router

router = create_signed_stream_router("/proxy", "/audio/{video_id}", "/proxy/audio")
