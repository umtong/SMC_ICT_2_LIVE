"""Official Bybit V5 one-minute acquisition for the sealed sweep/crowding run.

This module changes only the failed public-data transport.  Strategy, features,
labels, model, execution, sizing, costs and sequential periods remain frozen.
"""
from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .common import CachedDownloader, SourceGateError, month_range, sha256_json

BYBIT_KLINE_ENDPOINT = "https://api.bybit.com/v5/market/kline"
SOURCE_CORRECTION_ID = "CORRECTION-20260727-ML-SWEEP-BYBIT-V5-TRANSPORT-002"


def _utc_ms(value: pd.Timestamp) -> int:
    return int(value.value // 1_000_000)


def _month_bounds(
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    year: int,
    month: int,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    month_start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
    month_end = month_start + pd.offsets.MonthBegin(1)
    return max(start, month_start), min(end_exclusive, month_end)


def _canonical_line(timestamp_ms: int, row: Sequence[Any]) -> str:
    if len(row) < 6:
        raise SourceGateError(f"Bybit V5 kline row too short: {row}")
    if timestamp_ms % 60_000:
        raise SourceGateError(f"Bybit V5 non-minute timestamp: {timestamp_ms}")
    timestamp = pd.Timestamp(timestamp_ms, unit="ms", tz="UTC").strftime("%Y.%m.%d %H:%M")
    values = [str(row[index]) for index in range(1, 6)]
    try:
        numeric = [float(value) for value in values]
    except ValueError as exc:
        raise SourceGateError(f"Bybit V5 nonnumeric kline row: {row}") from exc
    if min(numeric[:4]) <= 0 or numeric[1] < max(numeric[0], numeric[3], numeric[2]) or numeric[2] > min(numeric[0], numeric[1], numeric[3]):
        raise SourceGateError(f"Bybit V5 impossible OHLC row: {row}")
    return ",".join([timestamp, *values]) + "\n"


def _write_deterministic_gzip(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    with temp.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(text.encode("utf-8"))
    temp.replace(path)


def download_bybit_interval_v5(
    downloader: CachedDownloader,
    symbol: str,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    relative_path: str,
) -> Path:
    """Download one interval from official V5 and emit the legacy canonical CSV shape."""
    path = downloader.cache_dir / relative_path
    manifest_path = path.with_suffix(path.suffix + ".source.json")
    if path.exists() and path.stat().st_size >= 128 and manifest_path.exists():
        return path

    start_ms = _utc_ms(start)
    end_exclusive_ms = _utc_ms(end_exclusive)
    cursor_end = end_exclusive_ms - 1
    rows_by_timestamp: dict[int, Sequence[Any]] = {}
    pages: list[dict[str, Any]] = []

    for page_number in range(1, 20_001):
        params: Mapping[str, Any] = {
            "category": "linear",
            "symbol": symbol,
            "interval": "1",
            "start": start_ms,
            "end": cursor_end,
            "limit": 1000,
        }
        payload = downloader.get_json(BYBIT_KLINE_ENDPOINT, params)
        if int(payload.get("retCode", -1)) != 0:
            raise SourceGateError(f"{symbol} Bybit V5 kline retCode: {payload}")
        page = payload.get("result", {}).get("list", []) or []
        if not page:
            break
        timestamps: list[int] = []
        for row in page:
            if len(row) < 6:
                raise SourceGateError(f"{symbol} Bybit V5 malformed kline row: {row}")
            timestamp_ms = int(row[0])
            timestamps.append(timestamp_ms)
            if start_ms <= timestamp_ms < end_exclusive_ms:
                rows_by_timestamp[timestamp_ms] = row
        oldest = min(timestamps)
        newest = max(timestamps)
        pages.append(
            {
                "page": page_number,
                "request_end_ms": cursor_end,
                "row_count": len(page),
                "oldest_ms": oldest,
                "newest_ms": newest,
                "payload_sha256": sha256_json(payload),
            }
        )
        if oldest <= start_ms:
            break
        if oldest > cursor_end:
            raise SourceGateError(f"{symbol} Bybit V5 pagination did not progress: {oldest}")
        cursor_end = oldest - 1
    else:
        raise SourceGateError(f"{symbol} Bybit V5 page ceiling exceeded")

    if not rows_by_timestamp:
        raise SourceGateError(
            f"{symbol} Bybit V5 returned no one-minute rows for {start.isoformat()} to {end_exclusive.isoformat()}"
        )
    ordered = sorted(rows_by_timestamp.items())
    text = "".join(_canonical_line(timestamp_ms, row) for timestamp_ms, row in ordered)
    _write_deterministic_gzip(path, text)
    manifest = {
        "schema_version": 1,
        "source_correction_id": SOURCE_CORRECTION_ID,
        "endpoint": BYBIT_KLINE_ENDPOINT,
        "category": "linear",
        "symbol": symbol,
        "interval": "1",
        "start": start.isoformat(),
        "end_exclusive": end_exclusive.isoformat(),
        "rows": len(ordered),
        "first_timestamp_ms": ordered[0][0],
        "last_timestamp_ms": ordered[-1][0],
        "pages": pages,
        "canonical_rows_sha256": sha256_json(
            [[timestamp_ms, *[str(row[index]) for index in range(1, 6)]] for timestamp_ms, row in ordered]
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def download_bybit_months_v5(
    downloader: CachedDownloader,
    symbols: Sequence[str],
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> dict[str, list[Path]]:
    paths: dict[str, list[Path]] = {symbol: [] for symbol in symbols}
    for symbol in symbols:
        for year, month in month_range(start, end_exclusive):
            interval_start, interval_end = _month_bounds(start, end_exclusive, year, month)
            if interval_start >= interval_end:
                continue
            inclusive_last = (interval_end - pd.Timedelta(days=1)).date().isoformat()
            filename = (
                f"{symbol}_1_{interval_start.date().isoformat()}_{inclusive_last}.csv.gz"
            )
            relative = f"bybit_v5/{symbol}/{year}/{filename}"
            paths[symbol].append(
                download_bybit_interval_v5(
                    downloader, symbol, interval_start, interval_end, relative
                )
            )
    return paths
