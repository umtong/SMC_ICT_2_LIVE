#!/usr/bin/env python3
"""Build a checksum-verified 2023 Binance USD-M five-minute metrics snapshot.

Only daily archives before 2024 are accepted. Every source observation receives
an explicit `available_time_ms = create_time + 5 minutes` field so downstream
research cannot use an OI snapshot before one full reported interval has passed.
Provider-missing numeric cells remain NaN; they are never future-filled.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import requests

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
BASE = "https://data.binance.vision/data/futures/um/daily/metrics"
EXPECTED_HEADER = (
    "create_time",
    "symbol",
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)
STEP_MS = 300_000
DELAY_MS = 300_000
CUTOFF_MS = 1_704_067_200_000  # 2024-01-01T00:00:00Z, exclusive source time


@dataclass(frozen=True)
class SourceRecord:
    symbol: str
    day: str
    url: str
    checksum_url: str
    bytes: int
    sha256: str
    expected_sha256: str
    rows: int
    invalid_oi_rows: int
    invalid_ratio_cells: int
    first_create_time_ms: int
    last_create_time_ms: int


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_day(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.year >= 2024:
        raise ValueError("pre-2024 metrics builder refuses 2024-or-later dates")
    return parsed


def day_range(start: str, end: str) -> list[str]:
    first = parse_day(start)
    last = parse_day(end)
    if first > last:
        raise ValueError("start must not exceed end")
    out: list[str] = []
    current = first
    while current <= last:
        out.append(current.isoformat())
        current += timedelta(days=1)
    return out


def get_bytes(url: str, timeout: int, attempts: int = 4) -> bytes:
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.content
        except Exception as exc:  # noqa: BLE001 - preserve final transport error
            error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"failed after {attempts} attempts: {url}: {error}")


def parse_checksum(payload: bytes, expected_name: str) -> str:
    text = payload.decode("utf-8-sig").strip()
    tokens = text.split()
    if len(tokens) < 2:
        raise RuntimeError(f"invalid checksum content: {text!r}")
    digest = tokens[0].lower()
    name = tokens[-1].lstrip("*")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise RuntimeError(f"invalid SHA-256 token: {digest!r}")
    if name != expected_name:
        raise RuntimeError(f"checksum filename mismatch: {name!r} != {expected_name!r}")
    return digest


def parse_float(value: str) -> float:
    stripped = value.strip()
    if stripped == "":
        return math.nan
    try:
        parsed = float(stripped)
    except ValueError:
        return math.nan
    return parsed if math.isfinite(parsed) else math.nan


def parse_positive_float(value: str) -> float:
    parsed = parse_float(value)
    return parsed if math.isfinite(parsed) and parsed > 0.0 else math.nan


def parse_archive(
    symbol: str,
    day: str,
    url: str,
    checksum_url: str,
    payload: bytes,
    expected_sha: str,
) -> tuple[SourceRecord, np.ndarray]:
    actual_sha = sha256_bytes(payload)
    if actual_sha != expected_sha:
        raise RuntimeError(f"{url}: SHA-256 mismatch {actual_sha} != {expected_sha}")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise RuntimeError(f"{url}: expected one CSV, found {members}")
        text = archive.read(members[0]).decode("utf-8-sig")

    reader = csv.reader(io.StringIO(text))
    try:
        header = tuple(next(reader))
    except StopIteration as exc:
        raise RuntimeError(f"{url}: empty CSV") from exc
    if header != EXPECTED_HEADER:
        raise RuntimeError(f"{url}: schema mismatch {header!r}")

    rows: list[list[float]] = []
    for row_number, row in enumerate(reader, start=2):
        if len(row) != len(EXPECTED_HEADER):
            raise RuntimeError(f"{url}: row {row_number} has {len(row)} columns")
        timestamp = datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
        create_time_ms = int(timestamp.timestamp() * 1000)
        if row[1] != symbol:
            raise RuntimeError(f"{url}: row symbol {row[1]!r} != {symbol!r}")
        rows.append(
            [
                float(create_time_ms),
                parse_positive_float(row[2]),
                parse_positive_float(row[3]),
                parse_float(row[4]),
                parse_float(row[5]),
                parse_float(row[6]),
                parse_float(row[7]),
            ]
        )
    if len(rows) != 288:
        raise RuntimeError(f"{url}: expected 288 five-minute rows, found {len(rows)}")
    array = np.asarray(rows, dtype=np.float64)
    times = array[:, 0].astype(np.int64)
    expected_first = int(
        datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000
    )
    if times[0] != expected_first or times[-1] != expected_first + 287 * STEP_MS:
        raise RuntimeError(f"{url}: daily boundary mismatch")
    if np.any(np.diff(times) != STEP_MS):
        raise RuntimeError(f"{url}: non-exact five-minute grid")
    if np.any(times >= CUTOFF_MS):
        raise RuntimeError(f"{url}: post-cutoff source observation")

    invalid_oi = ~np.all(np.isfinite(array[:, 1:3]), axis=1)
    invalid_ratio_cells = int(np.size(array[:, 3:]) - np.isfinite(array[:, 3:]).sum())
    record = SourceRecord(
        symbol=symbol,
        day=day,
        url=url,
        checksum_url=checksum_url,
        bytes=len(payload),
        sha256=actual_sha,
        expected_sha256=expected_sha,
        rows=len(array),
        invalid_oi_rows=int(invalid_oi.sum()),
        invalid_ratio_cells=invalid_ratio_cells,
        first_create_time_ms=int(times[0]),
        last_create_time_ms=int(times[-1]),
    )
    return record, array


def download_one(symbol: str, day: str, timeout: int) -> tuple[SourceRecord, np.ndarray]:
    filename = f"{symbol}-metrics-{day}.zip"
    url = f"{BASE}/{symbol}/{filename}"
    checksum_url = f"{url}.CHECKSUM"
    checksum_payload = get_bytes(checksum_url, timeout)
    expected_sha = parse_checksum(checksum_payload, filename)
    payload = get_bytes(url, timeout)
    return parse_archive(symbol, day, url, checksum_url, payload, expected_sha)


def build(out_dir: Path, days: Iterable[str], workers: int, timeout: int) -> None:
    days = list(days)
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = [(symbol, day) for symbol in SYMBOLS for day in days]
    collected: dict[str, list[tuple[SourceRecord, np.ndarray]]] = {
        symbol: [] for symbol in SYMBOLS
    }
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(download_one, symbol, day, timeout): (symbol, day)
            for symbol, day in tasks
        }
        for number, future in enumerate(as_completed(futures), start=1):
            symbol, day = futures[future]
            record, array = future.result()
            collected[symbol].append((record, array))
            if number % 50 == 0 or number == len(tasks):
                print(f"downloaded {number}/{len(tasks)} daily archives", flush=True)

    manifest: dict[str, object] = {
        "schema_version": 1,
        "dataset_id": "BINANCE_USDM_4ASSET_5M_METRICS_2023_R1",
        "provider": "Binance Vision official public archives",
        "market": "USD-M perpetual futures",
        "symbols": list(SYMBOLS),
        "source_timeframe": "5m",
        "source_information_cutoff": "2023-12-31T23:59:59.999Z",
        "causal_delay_ms": DELAY_MS,
        "missing_value_contract": (
            "Provider-missing or non-positive OI cells are preserved as NaN. They are never "
            "future-filled or interpolated; downstream event formation requires finite current "
            "and lagged OI and therefore skips only affected states."
        ),
        "causal_contract": (
            "Each metrics row is unusable until create_time + one complete reported "
            "five-minute interval. Downstream one-minute decisions then apply the project "
            "fixed 500 ms latency and next-observable-price rule."
        ),
        "columns": [
            "create_time_ms",
            "available_time_ms",
            "sum_open_interest",
            "sum_open_interest_value",
            "count_toptrader_long_short_ratio",
            "sum_toptrader_long_short_ratio",
            "count_long_short_ratio",
            "sum_taker_long_short_vol_ratio",
        ],
        "sources": [],
        "snapshots": [],
    }

    reference_times: np.ndarray | None = None
    for symbol in SYMBOLS:
        parts = sorted(collected[symbol], key=lambda item: item[0].day)
        if len(parts) != len(days):
            raise RuntimeError(f"{symbol}: source count {len(parts)} != {len(days)}")
        records = [item[0] for item in parts]
        array = np.vstack([item[1] for item in parts])
        order = np.argsort(array[:, 0], kind="stable")
        array = array[order]
        times = array[:, 0].astype(np.int64)
        if np.any(np.diff(times) != STEP_MS):
            bad = np.flatnonzero(np.diff(times) != STEP_MS)
            sample = [(int(times[i]), int(times[i + 1])) for i in bad[:10]]
            raise RuntimeError(f"{symbol}: non-exact annual five-minute grid: {sample}")
        if reference_times is None:
            reference_times = times
        elif not np.array_equal(reference_times, times):
            raise RuntimeError(f"{symbol}: annual timestamps do not align")

        valid_oi = np.all(np.isfinite(array[:, 1:3]), axis=1)
        path = out_dir / f"{symbol}_metrics_5m_2023.npz"
        np.savez_compressed(
            path,
            create_time_ms=times,
            available_time_ms=times + DELAY_MS,
            sum_open_interest=array[:, 1],
            sum_open_interest_value=array[:, 2],
            count_toptrader_long_short_ratio=array[:, 3],
            sum_toptrader_long_short_ratio=array[:, 4],
            count_long_short_ratio=array[:, 5],
            sum_taker_long_short_vol_ratio=array[:, 6],
        )
        manifest["sources"].extend(asdict(record) for record in records)
        manifest["snapshots"].append(
            {
                "symbol": symbol,
                "path": path.name,
                "rows": int(len(times)),
                "valid_oi_rows": int(valid_oi.sum()),
                "invalid_oi_rows": int((~valid_oi).sum()),
                "valid_oi_fraction": float(valid_oi.mean()),
                "invalid_optional_ratio_cells": int(
                    np.size(array[:, 3:]) - np.isfinite(array[:, 3:]).sum()
                ),
                "first_create_time_ms": int(times[0]),
                "last_create_time_ms": int(times[-1]),
                "first_available_time_ms": int(times[0] + DELAY_MS),
                "last_available_time_ms": int(times[-1] + DELAY_MS),
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )

    manifest_path = out_dir / "METRICS_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "METRICS_MANIFEST.sha256").write_text(
        f"{file_sha256(manifest_path)}  {manifest_path.name}\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(out_dir),
                "symbols": list(SYMBOLS),
                "daily_archives": len(tasks),
                "rows_per_symbol": int(0 if reference_times is None else len(reference_times)),
                "invalid_oi_rows": {
                    item["symbol"]: item["invalid_oi_rows"] for item in manifest["snapshots"]
                },
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2023-12-31")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    build(
        args.out,
        day_range(args.start, args.end),
        max(1, args.workers),
        args.timeout,
    )


if __name__ == "__main__":
    main()
