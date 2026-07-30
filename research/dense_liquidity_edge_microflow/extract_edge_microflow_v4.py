#!/usr/bin/env python3
"""V4 correction: retain only the post-entry part of the actual entry minute.

The V3 event/sensor semantics are unchanged.  These fields prevent an account
replay from using pre-entry highs/lows from the containing canonical minute.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_edge_microflow_v3 as base  # noqa: E402

_original = base.sensor_row


def sensor_row(*args, **kwargs):
    row = _original(*args, **kwargs)
    if row is None:
        return None
    stream = args[4] if len(args) > 4 else kwargs["stream"]
    entry_ts = pd.Timestamp(row["entry_ts"])
    minute_end = entry_ts.floor("min") + pd.Timedelta(minutes=1)
    post = stream[(stream["ts"] >= entry_ts) & (stream["ts"] < minute_end)]
    if post.empty:
        return None
    row.update(
        {
            "post_entry_minute_high": float(post["price"].max()),
            "post_entry_minute_low": float(post["price"].min()),
            "post_entry_minute_close": float(post.iloc[-1]["price"]),
            "post_entry_minute_last_ts": post.iloc[-1]["ts"].isoformat(),
            "post_entry_minute_trade_count": int(len(post)),
            "post_entry_minute_turnover": float(post["turnover"].sum()),
        }
    )
    return row


base.sensor_row = sensor_row

if __name__ == "__main__":
    raise SystemExit(base.main())
