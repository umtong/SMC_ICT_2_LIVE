from __future__ import annotations

import gzip
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from system.public_archive import (  # noqa: E402
    archive_filename,
    archive_url,
    iter_months,
    load_public_archive,
    parse_archive_bytes,
)


def _payload(rows: list[str]) -> bytes:
    return gzip.compress(("\n".join(rows) + "\n").encode("utf-8"))


def test_public_archive_filename_and_month_iteration_are_exact() -> None:
    months = iter_months("2023-01-15T00:00:00Z", "2023-03-01T00:00:00Z")
    assert [row.strftime("%Y-%m") for row in months] == ["2023-01", "2023-02"]
    assert archive_filename("BTCUSDT", 1, months[0]) == "BTCUSDT_1_2023-01-01_2023-01-31.csv.gz"
    assert archive_url("BTCUSDT", 5, months[1]).endswith("/BTCUSDT/2023/BTCUSDT_5_2023-02-01_2023-02-28.csv.gz")


def test_public_archive_bar_is_available_only_after_completion() -> None:
    frame = parse_archive_bytes(
        _payload(["2023.01.01 00:00,100,101,99,100.5,12"]),
        5,
    )
    assert frame.iloc[0]["bar_start"] == pd.Timestamp("2023-01-01T00:00:00Z")
    assert frame.index[0] == pd.Timestamp("2023-01-01T00:05:00Z")
    assert frame.iloc[0]["available_at_ms"] > frame.iloc[0]["start_time_ms"]


def test_month_boundary_bar_is_not_duplicated_across_files(tmp_path: Path) -> None:
    january = _payload(
        [
            "2023.01.31 23:59,100,101,99,100,1",
            "2023.02.01 00:00,100,101,99,100,1",
        ]
    )
    february = _payload(
        [
            "2023.02.01 00:00,100,101,99,100,1",
            "2023.02.01 00:01,100,101,99,100,1",
            "2023.03.01 00:00,100,101,99,100,1",
        ]
    )
    cache = tmp_path / "bybit_public_mt4" / "BTCUSDT" / "2023"
    cache.mkdir(parents=True)
    (cache / archive_filename("BTCUSDT", 1, "2023-01-01")).write_bytes(january)
    (cache / archive_filename("BTCUSDT", 1, "2023-02-01")).write_bytes(february)

    result = load_public_archive(
        tmp_path,
        "BTCUSDT",
        1,
        "2023-01-31T23:59:00Z",
        "2023-02-01T00:02:00Z",
    )
    starts = list(result.frame["bar_start"])
    assert starts == [
        pd.Timestamp("2023-01-31T23:59:00Z"),
        pd.Timestamp("2023-02-01T00:00:00Z"),
        pd.Timestamp("2023-02-01T00:01:00Z"),
    ]
    assert not result.frame.index.duplicated().any()
    assert result.records[0].raw_row_count == 2
    assert result.records[0].retained_row_count == 1
