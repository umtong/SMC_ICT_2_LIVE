from __future__ import annotations

import argparse
import calendar
import gzip
import hashlib
import io
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
MONTHS = ((2023, 12),) + tuple((2024, month) for month in range(1, 7))
BASE_URL = "https://public.bybit.com/kline_for_metatrader4"
USER_AGENT = "SMC_ICT_2_LIVE-donchian-2024h1-5m-aggregate/1.0"


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def month_bounds(year: int, month: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
    if month == 12:
        end = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
    else:
        end = pd.Timestamp(year=year, month=month + 1, day=1, tz="UTC")
    return start, end


def archive_name(symbol: str, interval: int, year: int, month: int) -> str:
    last_day = calendar.monthrange(year, month)[1]
    return f"{symbol}_{interval}_{year:04d}-{month:02d}-01_{year:04d}-{month:02d}-{last_day:02d}.csv.gz"


def archive_url(symbol: str, interval: int, year: int, month: int) -> str:
    return f"{BASE_URL}/{symbol}/{year}/{archive_name(symbol, interval, year, month)}"


def download(url: str, path: Path, session: requests.Session) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            response = session.get(url, timeout=(30, 180))
            response.raise_for_status()
            payload = response.content
            with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as handle:
                while handle.read(1 << 20):
                    pass
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(payload)
            tmp.replace(path)
            return {
                "url": url,
                "http_status": int(response.status_code),
                "bytes": len(payload),
                "sha256": sha256_bytes(payload),
            }
        except Exception as exc:  # pragma: no cover - network retry
            last_error = exc
            if attempt == 4:
                raise
            time.sleep(2**attempt)
    raise RuntimeError(last_error)


def parse_archive(path: Path, year: int, month: int) -> pd.DataFrame:
    raw = pd.read_csv(path, compression="gzip", header=None, low_memory=False)
    if raw.shape[1] < 6:
        raise ValueError(f"{path.name}: expected at least six columns, got {raw.shape[1]}")
    raw = raw.iloc[:, :6].copy()
    raw.columns = ["datetime", "open", "high", "low", "close", "volume"]
    dt = pd.to_datetime(raw["datetime"], format="%Y.%m.%d %H:%M", utc=True, errors="coerce")
    numeric = raw[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce").astype(float)
    valid = dt.notna() & numeric.notna().all(axis=1)
    frame = numeric.loc[valid].copy()
    frame.index = pd.DatetimeIndex(dt.loc[valid])
    start, end = month_bounds(year, month)
    frame = frame[(frame.index >= start) & (frame.index < end)].sort_index()
    if frame.empty:
        raise ValueError(f"{path.name}: no rows inside requested month")

    if frame.index.has_duplicates:
        duplicate_times = frame.index[frame.index.duplicated(keep=False)].unique()
        for timestamp in duplicate_times:
            rows = frame.loc[[timestamp]]
            if not np.allclose(rows.to_numpy(float), rows.iloc[[0]].to_numpy(float), rtol=0.0, atol=0.0, equal_nan=False):
                raise ValueError(f"{path.name}: conflicting duplicate at {timestamp}")
        frame = frame[~frame.index.duplicated(keep="last")]

    expected = pd.date_range(start, end, freq="5min", inclusive="left")
    missing = expected.difference(frame.index)
    extra = frame.index.difference(expected)
    if len(missing) or len(extra):
        raise ValueError(f"{path.name}: incomplete official 5m grid missing={len(missing)} extra={len(extra)}")
    frame = frame.reindex(expected)

    prices = frame[["open", "high", "low", "close"]]
    if (prices <= 0).any().any() or (frame["volume"] < 0).any():
        raise ValueError(f"{path.name}: non-positive price or negative volume")
    if not (frame["high"] >= frame[["open", "close", "low"]].max(axis=1)).all():
        raise ValueError(f"{path.name}: high invariant failed")
    if not (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)).all():
        raise ValueError(f"{path.name}: low invariant failed")
    return frame


def aggregate_hourly(frame: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    start, end = month_bounds(year, month)
    expected_5m = pd.date_range(start, end, freq="5min", inclusive="left")
    if not frame.index.equals(expected_5m):
        raise ValueError("aggregate input is not the exact requested 5m grid")
    groups = np.arange(len(frame), dtype=np.int64) // 12
    counts = frame.groupby(groups, sort=True).size().to_numpy()
    if len(counts) == 0 or not np.all(counts == 12):
        raise ValueError("an hourly bucket does not contain exactly twelve 5m bars")
    hourly = pd.DataFrame(
        {
            "open": frame["open"].groupby(groups).first().to_numpy(float),
            "high": frame["high"].groupby(groups).max().to_numpy(float),
            "low": frame["low"].groupby(groups).min().to_numpy(float),
            "close": frame["close"].groupby(groups).last().to_numpy(float),
            "volume": frame["volume"].groupby(groups).sum().to_numpy(float),
        },
        index=pd.date_range(start, end, freq="1h", inclusive="left"),
    )
    expected_hours = int((end - start) / pd.Timedelta(hours=1))
    if len(hourly) != expected_hours or not hourly.index.equals(pd.date_range(start, end, freq="1h", inclusive="left")):
        raise ValueError("hourly aggregation grid mismatch")
    return hourly


def format_number(value: float) -> str:
    if not np.isfinite(value):
        raise ValueError("cannot serialize non-finite value")
    return format(float(value), ".15g")


def write_hourly(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        for timestamp, row in frame.iterrows():
            fields = [
                timestamp.strftime("%Y.%m.%d %H:%M"),
                format_number(row["open"]),
                format_number(row["high"]),
                format_number(row["low"]),
                format_number(row["close"]),
                format_number(row["volume"]),
            ]
            handle.write(",".join(fields) + "\n")


def build(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    raw_root = output / "_raw5m"
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    records: list[dict[str, Any]] = []

    for symbol in SYMBOLS:
        symbol_dir = output / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)
        for stale in symbol_dir.glob(f"{symbol}_60_*.csv.gz"):
            stale.unlink()
        for year, month in MONTHS:
            source_name = archive_name(symbol, 5, year, month)
            source_path = raw_root / symbol / source_name
            source = download(archive_url(symbol, 5, year, month), source_path, session)
            five = parse_archive(source_path, year, month)
            hourly = aggregate_hourly(five, year, month)
            output_name = archive_name(symbol, 60, year, month)
            output_path = symbol_dir / output_name
            write_hourly(output_path, hourly)
            with gzip.open(output_path, "rt", encoding="utf-8") as handle:
                emitted_rows = sum(1 for line in handle if line.strip())
            if emitted_rows != len(hourly):
                raise ValueError(f"{output_name}: emitted row mismatch {emitted_rows} != {len(hourly)}")
            record = {
                "symbol": symbol,
                "year": year,
                "month": month,
                "mode": "official_5m_archive_aggregated_to_60m",
                "source_url": source["url"],
                "source_http_status": source["http_status"],
                "source_bytes": source["bytes"],
                "source_sha256": source["sha256"],
                "source_5m_rows": int(len(five)),
                "aggregation": "exact twelve contiguous completed 5m bars per UTC hour",
                "output_path": str(output_path),
                "output_bytes": output_path.stat().st_size,
                "output_sha256": sha256_file(output_path),
                "hourly_rows": int(len(hourly)),
                "first_timestamp": hourly.index[0].isoformat(),
                "last_timestamp": hourly.index[-1].isoformat(),
            }
            records.append(record)
            print(stable_json(record), flush=True)

    manifest = {
        "schema_version": 2,
        "transport": "BYBIT_OFFICIAL_MT4_5M_EXACT_AGGREGATION",
        "all_files": len(records),
        "archive_count": len(records),
        "api_fallback_count": 0,
        "symbols": list(SYMBOLS),
        "months": [f"{year:04d}-{month:02d}" for year, month in MONTHS],
        "gap_policy": "NO_IMPUTATION_REJECT_ANY_INCOMPLETE_5M_MONTH",
        "records": records,
    }
    (output / "bar_transport.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def self_test() -> None:
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    idx = pd.date_range(start, periods=24, freq="5min")
    base = np.arange(24, dtype=float) + 100.0
    frame = pd.DataFrame(
        {
            "open": base,
            "high": base + 2.0,
            "low": base - 1.0,
            "close": base + 1.0,
            "volume": np.ones(24),
        },
        index=idx,
    )
    groups = np.arange(len(frame)) // 12
    hourly = pd.DataFrame(
        {
            "open": frame["open"].groupby(groups).first().to_numpy(),
            "high": frame["high"].groupby(groups).max().to_numpy(),
            "low": frame["low"].groupby(groups).min().to_numpy(),
            "close": frame["close"].groupby(groups).last().to_numpy(),
            "volume": frame["volume"].groupby(groups).sum().to_numpy(),
        },
        index=pd.date_range(start, periods=2, freq="1h"),
    )
    assert hourly.iloc[0].to_dict() == {
        "open": 100.0,
        "high": 113.0,
        "low": 99.0,
        "close": 112.0,
        "volume": 12.0,
    }
    assert hourly.iloc[1]["open"] == 112.0
    assert hourly.iloc[1]["close"] == 124.0
    assert archive_name("BTCUSDT", 5, 2024, 2) == "BTCUSDT_5_2024-02-01_2024-02-29.csv.gz"
    print("SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        parser.error("--output is required unless --self-test is used")
    result = build(args.output)
    print(stable_json({"status": "PASS", "files": result["all_files"], "transport": result["transport"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
