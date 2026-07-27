#!/usr/bin/env python3
"""Run the caption collector without making yt-dlp metadata a hard gate.

YouTube may throttle a metadata request while its transcript endpoint remains
available. Returning an empty metadata mapping lets the base collector proceed
to youtube-transcript-api and youtube-transcript.ai, while retaining the seed
title and channel/video provenance from enumeration.
"""
from __future__ import annotations

import collect_channels as collector

_original_fetch_video_metadata = collector.fetch_video_metadata


def _fetch_video_metadata_or_empty(video_id: str) -> dict:
    try:
        return _original_fetch_video_metadata(video_id)
    except Exception as exc:  # caption-only fallbacks remain independently auditable
        collector.LOGGER.warning(
            "Metadata unavailable for %s; continuing with caption-only providers: %s",
            video_id,
            collector.safe_error(exc, 1000),
        )
        return {}


collector.fetch_video_metadata = _fetch_video_metadata_or_empty

if __name__ == "__main__":
    raise SystemExit(collector.main())
