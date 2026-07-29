#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
START = pd.Timestamp("2022-03-01T00:00:00Z")
END = pd.Timestamp("2024-01-01T00:00:00Z")
BASE = "https://data.binance.vision/data/futures/um/monthly"
KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "num_trades", "taker_buy_base_volume",
    "taker_buy_quote_volume", "ignore",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def months() -> list[pd.Timestamp]:
    return list(pd.date_range("2022-03-01", "2023-12-01", freq="MS", tz="UTC"))


def fetch(url: str, destination: Path, retries: int = 5) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size:
        return destination
    partial = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "SMC-ICT-aligned-continuation-audit/1.0"},
            )
            with urllib.request.urlopen(request, timeout=180) as response, partial.open("wb") as out:
                shutil.copyfileobj(response, out, length=1 << 20)
            partial.replace(destination)
            return destination
        except Exception as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            time.sleep(min(2 ** attempt, 16))
    raise RuntimeError(f"download failed: {url}: {last_error}")


def archive_url(symbol: str, month: pd.Timestamp, kind: str) -> tuple[str, str]:
    ym = month.strftime("%Y-%m")
    if kind == "klines":
        name = f"{symbol}-1m-{ym}.zip"
        return f"{BASE}/klines/{symbol}/1m/{name}", name
    if kind == "fundingRate":
        name = f"{symbol}-fundingRate-{ym}.zip"
        return f"{BASE}/fundingRate/{symbol}/{name}", name
    raise ValueError(kind)


def download_one(raw_root: Path, symbol: str, month: pd.Timestamp, kind: str) -> dict:
    url, name = archive_url(symbol, month, kind)
    destination = raw_root / kind / symbol / name
    checksum_path = destination.with_suffix(destination.suffix + ".CHECKSUM")
    fetch(url + ".CHECKSUM", checksum_path)
    expected = checksum_path.read_text(encoding="utf-8").strip().split()[0]
    fetch(url, destination)
    actual = sha256_file(destination)
    if actual != expected:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"checksum mismatch {destination}: {actual} != {expected}")
    return {
        "symbol": symbol,
        "month": month.strftime("%Y-%m"),
        "kind": kind,
        "url": url,
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": actual,
    }


def read_single_csv(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected exactly one CSV, got {names}")
        raw = archive.read(names[0])
    return pd.read_csv(io.BytesIO(raw), header=None)


def materialize_klines(raw_root: Path, symbol: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted((raw_root / "klines" / symbol).glob("*.zip")):
        frame = read_single_csv(path)
        if frame.shape[1] < 11:
            raise ValueError(f"{path}: unexpected kline width {frame.shape[1]}")
        if str(frame.iloc[0, 0]).strip().lower() in {"open_time", "open time"}:
            frame = frame.iloc[1:].reset_index(drop=True)
        frame = frame.iloc[:, :12]
        frame.columns = KLINE_COLUMNS
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    for column in KLINE_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="raise")
    out["timestamp"] = pd.to_datetime(out.open_time.astype("int64"), unit="ms", utc=True)
    out = out[(out.timestamp >= START) & (out.timestamp < END)].copy()
    out = out[[
        "timestamp", "open", "high", "low", "close", "volume", "quote_volume",
        "num_trades", "taker_buy_base_volume", "taker_buy_quote_volume",
    ]]
    out = out.sort_values("timestamp").drop_duplicates("timestamp", keep=False).reset_index(drop=True)
    if out.timestamp.duplicated().any() or not out.timestamp.is_monotonic_increasing:
        raise ValueError(f"{symbol}: invalid timestamp ordering")
    return out


def materialize_funding(raw_root: Path, symbol: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted((raw_root / "fundingRate" / symbol).glob("*.zip")):
        frame = read_single_csv(path)
        if frame.empty:
            continue
        first = str(frame.iloc[0, 0]).strip().lower()
        if "calc" in first or "fund" in first or "time" in first:
            frame = frame.iloc[1:].reset_index(drop=True)
        if frame.shape[1] < 2:
            raise ValueError(f"{path}: unexpected funding width {frame.shape[1]}")
        timestamp = pd.to_numeric(frame.iloc[:, 0], errors="raise").astype("int64")
        rate = pd.to_numeric(frame.iloc[:, -1], errors="raise")
        frames.append(pd.DataFrame({
            "timestamp": pd.to_datetime(timestamp, unit="ms", utc=True),
            "funding_rate": rate,
        }))
    out = pd.concat(frames, ignore_index=True)
    out = out[(out.timestamp >= START) & (out.timestamp < END)]
    return out.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    raw_root = args.root / "raw"
    prepared = args.root / "prepared"
    prepared.mkdir(parents=True, exist_ok=True)

    jobs = [(symbol, month, kind) for symbol in SYMBOLS for month in months() for kind in ("klines", "fundingRate")]
    records: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(download_one, raw_root, symbol, month, kind): (symbol, month, kind)
            for symbol, month, kind in jobs
        }
        for number, future in enumerate(as_completed(futures), 1):
            records.append(future.result())
            if number % 20 == 0:
                print(f"downloaded {number}/{len(jobs)}", flush=True)

    prepared_records = []
    for symbol in SYMBOLS:
        minute = materialize_klines(raw_root, symbol)
        funding = materialize_funding(raw_root, symbol)
        minute_path = prepared / f"{symbol}_minute.parquet"
        funding_path = prepared / f"{symbol}_funding.parquet"
        minute.to_parquet(minute_path, index=False)
        funding.to_parquet(funding_path, index=False)
        prepared_records.append({
            "symbol": symbol,
            "minute_rows": len(minute),
            "minute_start": minute.timestamp.min().isoformat(),
            "minute_end": minute.timestamp.max().isoformat(),
            "minute_sha256": sha256_file(minute_path),
            "funding_rows": len(funding),
            "funding_sha256": sha256_file(funding_path),
        })
        print(symbol, len(minute), len(funding), flush=True)

    manifest = {
        "schema_version": 1,
        "source": "Binance Vision official USD-M monthly archives",
        "interval": [START.isoformat(), END.isoformat()],
        "raw_records": sorted(records, key=lambda row: (row["symbol"], row["month"], row["kind"])),
        "prepared": prepared_records,
    }
    (args.root / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
