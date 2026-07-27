#!/usr/bin/env python3
"""Run the caption collector without making yt-dlp metadata a hard gate.

YouTube may throttle a metadata request while its transcript endpoint remains
available. The first metadata failure opens a process-wide circuit breaker, so
later videos proceed immediately to youtube-transcript-api and
youtube-transcript.ai instead of repeating a long anti-bot retry path. Seed
titles and channel/video provenance still come from channel enumeration.
"""
from __future__ import annotations

import collect_channels as collector

_original_fetch_video_metadata = collector.fetch_video_metadata
_metadata_circuit_open = False


def _fetch_video_metadata_or_empty(video_id: str) -> dict:
    global _metadata_circuit_open
    if _metadata_circuit_open:
        return {}
    try:
        return _original_fetch_video_metadata(video_id)
    except Exception as exc:  # caption-only fallbacks remain independently auditable
        _metadata_circuit_open = True
        collector.LOGGER.warning(
            "Metadata unavailable for %s; opening circuit and continuing with caption-only providers: %s",
            video_id,
            collector.safe_error(exc, 1000),
        )
        return {}


collector.fetch_video_metadata = _fetch_video_metadata_or_empty

if __name__ == "__main__":
    raise SystemExit(collector.main())
