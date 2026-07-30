from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from system.canonical_adapter import causal_asof_join  # noqa: E402


def test_repeated_causal_joins_use_unique_stream_source_timestamps() -> None:
    base = pd.DataFrame(
        {
            "available_at_ms": pd.array([300_000, 600_000], dtype="Int64"),
            "close": [101.0, 102.0],
        },
        index=pd.to_datetime(["1970-01-01T00:05:00Z", "1970-01-01T00:10:00Z"]),
    )
    mark = pd.DataFrame(
        {
            "available_at_ms": np.asarray([299_999, 599_999], dtype=np.int64),
            "mark_close": [100.5, 101.5],
        },
        index=pd.to_datetime(["1970-01-01T00:04:00Z", "1970-01-01T00:09:00Z"]),
    )
    index = pd.DataFrame(
        {
            "available_at_ms": np.asarray([299_998, 599_998], dtype=np.int64),
            "index_close": [100.4, 101.4],
        },
        index=pd.to_datetime(["1970-01-01T00:03:00Z", "1970-01-01T00:08:00Z"]),
    )

    joined = causal_asof_join(causal_asof_join(base, mark), index)

    assert joined["available_at_ms"].dtype == np.dtype("int64")
    assert joined["mark_close"].tolist() == [100.5, 101.5]
    assert joined["index_close"].tolist() == [100.4, 101.4]
    assert "mark_close_source_timestamp" in joined.columns
    assert "index_close_source_timestamp" in joined.columns
    assert not any(name.endswith(("_x", "_y")) for name in joined.columns)
