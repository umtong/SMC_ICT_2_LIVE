from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from .common import SourceGateError
from .source_v5 import download_bybit_interval_v5


class FakeDownloader:
    def __init__(self, cache_dir: Path, rows: list[list[str]], ret_code: int = 0) -> None:
        self.cache_dir = cache_dir
        self.rows = rows
        self.ret_code = ret_code
        self.calls: list[dict[str, object]] = []

    def get_json(self, url: str, params: dict[str, object]) -> dict[str, object]:
        self.calls.append(dict(params))
        if self.ret_code:
            return {"retCode": self.ret_code, "retMsg": "synthetic failure", "result": {"list": []}}
        start = int(params["start"])
        end = int(params["end"])
        eligible = [row for row in self.rows if start <= int(row[0]) <= end]
        eligible.sort(key=lambda row: int(row[0]), reverse=True)
        return {"retCode": 0, "retMsg": "OK", "result": {"list": eligible[:2]}}


def test_v5_paginates_and_emits_sorted_legacy_shape(tmp_path: Path) -> None:
    start = pd.Timestamp("2023-01-01T00:00:00Z")
    rows: list[list[str]] = []
    for offset in range(4):
        timestamp_ms = int((start + pd.Timedelta(minutes=offset)).value // 1_000_000)
        price = 100.0 + offset
        rows.append(
            [
                str(timestamp_ms),
                str(price),
                str(price + 1),
                str(price - 1),
                str(price + 0.5),
                str(10 + offset),
                str(1000 + offset),
            ]
        )
    downloader = FakeDownloader(tmp_path, rows)
    path = download_bybit_interval_v5(
        downloader,
        "BTCUSDT",
        start,
        start + pd.Timedelta(minutes=4),
        "bybit_v5/BTCUSDT/2023/test.csv.gz",
    )
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        lines = handle.readlines()
    assert [line.split(",", 1)[0] for line in lines] == [
        "2023.01.01 00:00",
        "2023.01.01 00:01",
        "2023.01.01 00:02",
        "2023.01.01 00:03",
    ]
    assert len(downloader.calls) == 2
    assert int(downloader.calls[1]["end"]) == int(rows[2][0]) - 1
    manifest = json.loads(path.with_suffix(path.suffix + ".source.json").read_text())
    assert manifest["rows"] == 4
    assert manifest["source_correction_id"].endswith("002")
    assert len(manifest["pages"]) == 2


def test_v5_retcode_fails_closed(tmp_path: Path) -> None:
    start = pd.Timestamp("2023-01-01T00:00:00Z")
    downloader = FakeDownloader(tmp_path, [], ret_code=10001)
    with pytest.raises(SourceGateError, match="retCode"):
        download_bybit_interval_v5(
            downloader,
            "ETHUSDT",
            start,
            start + pd.Timedelta(minutes=1),
            "bybit_v5/ETHUSDT/2023/test.csv.gz",
        )
