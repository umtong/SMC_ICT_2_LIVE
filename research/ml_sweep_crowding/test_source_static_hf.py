from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd

from .source_static_hf import _normalize_funding, parse_bybit_one_minute_static


def test_static_price_coverage_begins_at_first_observed_minute(tmp_path: Path) -> None:
    path = tmp_path / "ETHUSDT_1_2021-03-01_2021-03-31.csv.gz"
    rows = [
        "2021.03.01 00:00,100,101,99,100.5,10\n",
        "2021.03.01 00:01,100.5,102,100,101,11\n",
        "2021.03.01 00:02,101,103,100.5,102,12\n",
    ]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.writelines(rows)
    frame, coverage, _fingerprint, effective_start = parse_bybit_one_minute_static(
        "ETHUSDT",
        [path],
        pd.Timestamp("2021-01-01T00:00:00Z"),
        pd.Timestamp("2021-03-01T00:03:00Z"),
        0.995,
    )
    assert effective_start == pd.Timestamp("2021-03-01T00:00:00Z")
    assert coverage == 1.0
    assert len(frame) == 3


def test_funding_normalizer_uses_close_series() -> None:
    source = pd.DataFrame(
        {
            "date": pd.date_range("2022-01-01", periods=3, freq="8h", tz="UTC"),
            "open": [0.0001, 0.0002, -0.0001],
            "high": [0.0001, 0.0002, -0.0001],
            "low": [0.0001, 0.0002, -0.0001],
            "close": [0.0001, 0.0002, -0.0001],
            "volume": [0.0, 0.0, 0.0],
        }
    )
    normalized = _normalize_funding(source)
    assert list(normalized.columns) == ["funding_rate"]
    assert normalized.index.tz is not None
    assert normalized["funding_rate"].tolist() == [0.0001, 0.0002, -0.0001]
