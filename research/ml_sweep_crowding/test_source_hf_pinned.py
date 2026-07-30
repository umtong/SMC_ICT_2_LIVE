from __future__ import annotations

from pathlib import Path

import pandas as pd

from .source_hf_pinned import load_pinned_one_minute, normalize_funding_open


def test_pinned_one_minute_exact_grid(tmp_path: Path) -> None:
    start = pd.Timestamp("2023-01-01T00:00:00Z")
    frame = pd.DataFrame(
        {
            "date": pd.date_range(start, periods=3, freq="1min"),
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    path = tmp_path / "price.parquet"
    frame.to_parquet(path, index=False)
    loaded, coverage, fingerprint = load_pinned_one_minute(
        path,
        "BTCUSDT",
        start,
        start + pd.Timedelta(minutes=3),
        0.995,
    )
    assert coverage == 1.0
    assert len(loaded) == 3
    assert loaded.index[0] == start
    assert len(fingerprint) == 64


def test_funding_open_column_is_actual_rate() -> None:
    rates = [
        0.0001,
        -0.0002,
        0.0003,
        -0.0004,
        0.0005,
        -0.0006,
        0.0007,
        -0.0008,
        0.0009,
        -0.0010,
        0.0011,
        -0.0012,
    ]
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2022-01-01", periods=12, freq="8h", tz="UTC"),
            "open": rates,
            "high": [0.0] * 12,
            "low": [0.0] * 12,
            "close": [0.0] * 12,
            "volume": [0.0] * 12,
        }
    )
    normalized = normalize_funding_open(frame)
    assert normalized.index[0] == pd.Timestamp("2022-01-01T00:00:00Z")
    assert normalized["funding_rate"].nunique() == 12
    assert normalized["funding_rate"].iloc[1] == -0.0002
