from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import source_probe as probe


def test_timestamp_normalization() -> None:
    assert probe.normalize_timestamp_ms("1640995200000") == 1_640_995_200_000
    assert probe.normalize_timestamp_ms("1640995200000000") == 1_640_995_200_000
    assert probe.normalize_timestamp_ms("1640995200000000000") == 1_640_995_200_000


def test_archive_urls_are_frozen() -> None:
    agg, checksum, partition = probe.archive_urls("BTCUSDT", "aggTrades", "2022-01-01")
    assert agg.endswith("/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2022-01-01.zip")
    assert checksum == f"{agg}.CHECKSUM"
    assert partition == "2022-01-01"
    funding, funding_checksum, month = probe.archive_urls("BTCUSDT", "fundingRate", "2022-01-01")
    assert funding.endswith("/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2022-01.zip")
    assert funding_checksum == f"{funding}.CHECKSUM"
    assert month == "2022-01"


def test_headerless_aggtrade_zip(tmp_path: Path) -> None:
    archive = tmp_path / "agg.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(
            "BTCUSDT-aggTrades-2022-01-01.csv",
            "1,100.0,2.0,1,1,1640995200000,false\n"
            "2,100.1,3.0,2,2,1640995200100,true\n",
        )
    result = probe.inspect_zip(archive, "aggTrades")
    assert result["row_count"] == 2
    assert result["timestamp_column"] == "c5"
    assert result["timestamp_monotonic"] is True
    assert result["minimum_width"] == 7


def test_header_funding_zip(tmp_path: Path) -> None:
    archive = tmp_path / "funding.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(
            "BTCUSDT-fundingRate-2022-01.csv",
            "calc_time,funding_interval_hours,last_funding_rate\n"
            "1640995200000,8,0.0001\n"
            "1641024000000,8,-0.0002\n",
        )
    result = probe.inspect_zip(archive, "fundingRate")
    assert result["row_count"] == 2
    assert result["timestamp_column"] == "calc_time"
    assert result["last_timestamp_ms"] == 1_641_024_000_000


def test_checksum_parser() -> None:
    digest = hashlib.sha256(b"payload").hexdigest()
    assert probe.parse_expected_checksum(f"{digest}  file.zip\n".encode()) == digest
    assert probe.parse_expected_checksum(b"not-a-checksum") is None
