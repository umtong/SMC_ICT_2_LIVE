#!/usr/bin/env python3
from __future__ import annotations

import source_gate as gate


def timestamp_column(frame):
    priorities = [
        "timestamp", "block_timestamp", "block_time", "blocktimestamp", "blockts",
        "blocktime", "iso", "time", "date", "datetime",
    ]
    lowered = {str(c).lower(): str(c) for c in frame.columns}
    for name in priorities:
        if name in lowered:
            return lowered[name]
    for c in frame.columns:
        low = str(c).lower()
        if "timestamp" in low or "block_time" in low or low.endswith("ts"):
            return str(c)
    return None


gate.timestamp_column = timestamp_column
raise SystemExit(gate.main())
