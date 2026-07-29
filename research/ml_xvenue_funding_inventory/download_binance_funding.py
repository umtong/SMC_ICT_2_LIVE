#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
MONTHS = pd.date_range("2021-01-01", "2023-12-01", freq="MS", tz="UTC")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get(session: requests.Session, url: str) -> bytes:
    last = None
    for attempt in range(7):
        response = session.get(url, timeout=90)
        if response.status_code == 200:
            return response.content
        last = f"{response.status_code} {response.text[:200]}"
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"download failed {url}: {last}")


def parse_archive(raw: bytes, symbol: str, month: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = [n for n in zf.namelist() if not n.endswith('/')]
        if len(names) != 1:
            raise ValueError(f"{symbol} {month}: unexpected archive names {names}")
        csv_raw = zf.read(names[0])
    frame = pd.read_csv(io.BytesIO(csv_raw))
    lowered = {str(c).lower(): c for c in frame.columns}
    time_col = lowered.get("calc_time") or lowered.get("funding_time") or frame.columns[0]
    rate_col = lowered.get("last_funding_rate") or lowered.get("funding_rate") or frame.columns[-1]
    out = pd.DataFrame({
        "symbol": symbol,
        "funding_time_ms": pd.to_numeric(frame[time_col], errors="raise").astype("int64"),
        "funding_rate": pd.to_numeric(frame[rate_col], errors="raise"),
    })
    out["funding_time"] = pd.to_datetime(out.funding_time_ms, unit="ms", utc=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-cross-venue-funding/1.0"})
    manifest = {"schema_version": 1, "provider": "Binance Vision official USD-M archives", "base": BASE, "symbols": {}}
    for symbol in SYMBOLS:
        frames = []
        files = []
        for month in MONTHS:
            ym = month.strftime("%Y-%m")
            name = f"{symbol}-fundingRate-{ym}.zip"
            url = f"{BASE}/{symbol}/{name}"
            checksum_raw = get(session, url + ".CHECKSUM")
            expected = checksum_raw.decode("utf-8").strip().split()[0]
            raw = get(session, url)
            actual = sha256(raw)
            if actual != expected:
                raise RuntimeError(f"checksum mismatch {name}: {actual} != {expected}")
            frames.append(parse_archive(raw, symbol, ym))
            files.append({"name": name, "url": url, "bytes": len(raw), "sha256": actual, "checksum_sha256": sha256(checksum_raw)})
            print(symbol, ym, len(frames[-1]), flush=True)
        frame = pd.concat(frames, ignore_index=True).sort_values("funding_time_ms").drop_duplicates("funding_time_ms", keep="last")
        csv_path = args.output / f"{symbol}_binance_funding_2021_2023.csv"
        parquet_path = args.output / f"{symbol}_binance_funding_2021_2023.parquet"
        frame.to_csv(csv_path, index=False)
        frame.to_parquet(parquet_path, index=False)
        manifest["symbols"][symbol] = {
            "rows": len(frame),
            "start": frame.funding_time.min().isoformat(),
            "end": frame.funding_time.max().isoformat(),
            "csv_sha256": sha256(csv_path.read_bytes()),
            "parquet_sha256": sha256(parquet_path.read_bytes()),
            "files": files,
        }
    (args.output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
