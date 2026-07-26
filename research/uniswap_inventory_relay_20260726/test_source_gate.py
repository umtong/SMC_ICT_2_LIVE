from __future__ import annotations

from pathlib import Path

import pandas as pd

import source_gate as s


def test_parquet_entries() -> None:
    payload = {"parquet_files": [{"url": "https://x/a.parquet", "filename": "a.parquet"}]}
    assert s.parquet_entries(payload)[0]["filename"] == "a.parquet"


def test_relevant_block_entries() -> None:
    payload = [
        {"type": "file", "path": "blocks/ethereum__blocks__12200000_to_12400000.parquet"},
        {"type": "file", "path": "blocks/ethereum__blocks__19000000_to_19100000.parquet"},
    ]
    rows = s.relevant_block_entries(payload)
    assert len(rows) == 1
    assert rows[0]["lo"] == 12_200_000


def test_bybit_url() -> None:
    url = s.bybit_month_url("ETHUSDT", 5, 2023, 12, 31)
    assert url.endswith("/ETHUSDT/2023/ETHUSDT_5_2023-12-01_2023-12-31.csv.gz")


def test_inspect_bybit_headerless(tmp_path: Path) -> None:
    path = tmp_path / "sample.csv.gz"
    rows = [[f"2023-01-01 00:{i:02d}:00", 100, 101, 99, 100.5, 10] for i in range(60)]
    rows *= 3
    pd.DataFrame(rows).to_csv(path, index=False, header=False, compression="gzip")
    result = s.inspect_bybit(path)
    assert result["valid_sample_rows"] >= 100


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "x"
    path.write_bytes(b"abc")
    assert s.sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
