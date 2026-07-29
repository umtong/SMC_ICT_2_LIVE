#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
START = pd.Timestamp("2021-01-01T00:00:00Z")
END = pd.Timestamp("2024-01-01T00:00:00Z")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch_symbol(symbol: str, session: requests.Session) -> tuple[pd.DataFrame, list[dict]]:
    start_ms = int(START.timestamp() * 1000)
    end_ms = int(END.timestamp() * 1000) - 1
    rows: list[dict] = []
    pages: list[dict] = []
    cursor = start_ms
    while cursor <= end_ms:
        params = {"symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": 1000}
        response = None
        for attempt in range(6):
            response = session.get(BASE_URL, params=params, timeout=60)
            if response.status_code == 200:
                break
            time.sleep(min(2 ** attempt, 20))
        assert response is not None
        response.raise_for_status()
        raw = response.content
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"unexpected response for {symbol}: {payload}")
        pages.append({
            "request_url": response.url,
            "status": response.status_code,
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
            "row_count": len(payload),
        })
        if not payload:
            break
        rows.extend(payload)
        last = int(payload[-1]["fundingTime"])
        if last < cursor:
            raise RuntimeError("non-advancing funding cursor")
        cursor = last + 1
        if len(payload) < 1000:
            break
        time.sleep(0.15)
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError(f"empty funding series {symbol}")
    frame = frame[["symbol", "fundingTime", "fundingRate", "markPrice"]].copy()
    frame["funding_time_ms"] = pd.to_numeric(frame.pop("fundingTime"), errors="raise").astype("int64")
    frame["funding_rate"] = pd.to_numeric(frame.pop("fundingRate"), errors="raise")
    frame["mark_price"] = pd.to_numeric(frame.pop("markPrice"), errors="coerce")
    frame["funding_time"] = pd.to_datetime(frame.funding_time_ms, unit="ms", utc=True)
    frame = frame[(frame.funding_time >= START) & (frame.funding_time < END)]
    frame = frame.sort_values("funding_time_ms").drop_duplicates("funding_time_ms", keep="last").reset_index(drop=True)
    return frame, pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-cross-venue-funding/1.0"})
    manifest = {
        "schema_version": 1,
        "provider": "Binance USD-M Futures REST API",
        "endpoint": BASE_URL,
        "start": START.isoformat(),
        "end_exclusive": END.isoformat(),
        "symbols": {},
    }
    for symbol in SYMBOLS:
        frame, pages = fetch_symbol(symbol, session)
        csv_path = args.output / f"{symbol}_binance_funding_2021_2023.csv"
        parquet_path = args.output / f"{symbol}_binance_funding_2021_2023.parquet"
        frame.to_csv(csv_path, index=False)
        frame.to_parquet(parquet_path, index=False)
        manifest["symbols"][symbol] = {
            "rows": len(frame),
            "start": frame.funding_time.min().isoformat(),
            "end": frame.funding_time.max().isoformat(),
            "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            "parquet_sha256": hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
            "pages": pages,
        }
        print(symbol, len(frame), frame.funding_time.min(), frame.funding_time.max())
    (args.output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
