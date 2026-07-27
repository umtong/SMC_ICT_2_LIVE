from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

BASE_URLS = (
    "https://api.bybit.com",
    "https://api.bytick.com",
)


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


@dataclass
class FetchStats:
    endpoint: str
    symbol: str
    pages: int = 0
    rows_raw: int = 0
    retries: int = 0
    base_url: str = ""


class BybitClient:
    def __init__(self, *, timeout: int = 30, min_interval: float = 0.08) -> None:
        self.timeout = timeout
        self.min_interval = min_interval
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "SMC-ICT-causal-research/1.0",
                "Accept": "application/json",
            }
        )
        self._last_request = 0.0

    def get(self, endpoint: str, params: dict[str, Any], stats: FetchStats) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(9):
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            base = BASE_URLS[attempt % len(BASE_URLS)]
            url = f"{base}{endpoint}"
            try:
                self._last_request = time.monotonic()
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code in {403, 429, 500, 502, 503, 504}:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
                response.raise_for_status()
                payload = response.json()
                if int(payload.get("retCode", -1)) != 0:
                    raise RuntimeError(f"Bybit retCode={payload.get('retCode')} retMsg={payload.get('retMsg')}")
                stats.base_url = base
                return payload
            except Exception as exc:
                last_error = exc
                stats.retries += 1
                time.sleep(min(12.0, (2**attempt) * 0.35 + random.random() * 0.25))
        raise RuntimeError(f"GET {endpoint} failed after retries: {last_error}")


def fetch_klines(
    client: BybitClient,
    *,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms_exclusive: int,
) -> tuple[pd.DataFrame, FetchStats]:
    endpoint = "/v5/market/kline"
    stats = FetchStats(endpoint=endpoint, symbol=symbol)
    interval_minutes = int(interval)
    step_ms = interval_minutes * 60_000
    cursor_end = end_ms_exclusive - 1
    chunks: list[pd.DataFrame] = []
    seen_oldest: int | None = None
    while cursor_end >= start_ms:
        payload = client.get(
            endpoint,
            {
                "category": "linear",
                "symbol": symbol,
                "interval": interval,
                "start": start_ms,
                "end": cursor_end,
                "limit": 1000,
            },
            stats,
        )
        rows = payload.get("result", {}).get("list") or []
        stats.pages += 1
        stats.rows_raw += len(rows)
        if not rows:
            break
        frame = pd.DataFrame(
            rows,
            columns=["timestamp_ms", "open", "high", "low", "close", "volume", "turnover"],
        )
        frame["timestamp_ms"] = pd.to_numeric(frame["timestamp_ms"], errors="raise").astype("int64")
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            frame[col] = pd.to_numeric(frame[col], errors="raise").astype("float64")
        frame = frame[(frame["timestamp_ms"] >= start_ms) & (frame["timestamp_ms"] < end_ms_exclusive)]
        if not frame.empty:
            chunks.append(frame)
        oldest = min(int(row[0]) for row in rows)
        if seen_oldest is not None and oldest >= seen_oldest:
            raise RuntimeError(f"Kline pagination made no backward progress for {symbol}: {oldest}")
        seen_oldest = oldest
        if oldest <= start_ms:
            break
        cursor_end = oldest - 1
        if stats.pages % 100 == 0:
            print(
                f"{symbol} kline pages={stats.pages} rows={stats.rows_raw} oldest={utc_iso(oldest)} retries={stats.retries}",
                flush=True,
            )
    if not chunks:
        raise RuntimeError(f"No kline data returned for {symbol}")
    data = pd.concat(chunks, ignore_index=True)
    data = data.drop_duplicates("timestamp_ms", keep="last").sort_values("timestamp_ms").reset_index(drop=True)
    expected = pd.RangeIndex(start_ms, end_ms_exclusive, step_ms)
    observed = pd.Index(data["timestamp_ms"].astype("int64"))
    missing = expected.difference(observed)
    data.attrs["missing_count"] = int(len(missing))
    data.attrs["missing_first"] = [int(value) for value in missing[:20]]
    return data, stats


def fetch_funding(
    client: BybitClient,
    *,
    symbol: str,
    start_ms: int,
    end_ms_exclusive: int,
) -> tuple[pd.DataFrame, FetchStats]:
    endpoint = "/v5/market/funding/history"
    stats = FetchStats(endpoint=endpoint, symbol=symbol)
    cursor_end = end_ms_exclusive - 1
    rows_out: list[dict[str, Any]] = []
    seen_oldest: int | None = None
    while cursor_end >= start_ms:
        payload = client.get(
            endpoint,
            {
                "category": "linear",
                "symbol": symbol,
                "startTime": start_ms,
                "endTime": cursor_end,
                "limit": 200,
            },
            stats,
        )
        rows = payload.get("result", {}).get("list") or []
        stats.pages += 1
        stats.rows_raw += len(rows)
        if not rows:
            break
        for row in rows:
            ts = int(row["fundingRateTimestamp"])
            if start_ms <= ts < end_ms_exclusive:
                rows_out.append(
                    {
                        "timestamp_ms": ts,
                        "funding_rate": float(row["fundingRate"]),
                    }
                )
        oldest = min(int(row["fundingRateTimestamp"]) for row in rows)
        if seen_oldest is not None and oldest >= seen_oldest:
            break
        seen_oldest = oldest
        if oldest <= start_ms:
            break
        cursor_end = oldest - 1
    data = pd.DataFrame(rows_out, columns=["timestamp_ms", "funding_rate"])
    if not data.empty:
        data = data.drop_duplicates("timestamp_ms", keep="last").sort_values("timestamp_ms").reset_index(drop=True)
    return data, stats


def fetch_instrument(client: BybitClient, symbol: str) -> tuple[dict[str, Any], FetchStats]:
    endpoint = "/v5/market/instruments-info"
    stats = FetchStats(endpoint=endpoint, symbol=symbol)
    payload = client.get(endpoint, {"category": "linear", "symbol": symbol}, stats)
    rows = payload.get("result", {}).get("list") or []
    if not rows:
        raise RuntimeError(f"No instrument info for {symbol}")
    return rows[0], stats


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_utc(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def self_test() -> None:
    assert parse_utc("2024-01-01T00:00:00Z") == 1704067200000
    assert utc_iso(1704067200000).startswith("2024-01-01T00:00:00")
    fake = pd.DataFrame({"timestamp_ms": [0, 300_000, 600_000]})
    expected = pd.RangeIndex(0, 900_000, 300_000)
    assert len(expected.difference(pd.Index(fake["timestamp_ms"]))) == 0
    print("self-test: ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download causal Bybit linear perpetual research bars.")
    parser.add_argument("--output", type=Path, default=Path("artifact/bybit_data"))
    parser.add_argument("--start", default="2021-01-01T00:00:00Z")
    parser.add_argument("--end-exclusive", default="2026-07-01T00:00:00Z")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--interval", default="5")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    start_ms = parse_utc(args.start)
    end_ms = parse_utc(args.end_exclusive)
    if start_ms >= end_ms:
        raise SystemExit("start must be before end-exclusive")
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    client = BybitClient()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "source": "Bybit V5 public market API",
        "category": "linear",
        "interval_minutes": int(args.interval),
        "start_ms": start_ms,
        "start_utc": utc_iso(start_ms),
        "end_ms_exclusive": end_ms,
        "end_utc_exclusive": utc_iso(end_ms),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "symbols": {},
    }
    for symbol in args.symbols:
        print(f"Downloading {symbol} {args.interval}m {args.start} -> {args.end_exclusive}", flush=True)
        bars, bar_stats = fetch_klines(
            client,
            symbol=symbol,
            interval=args.interval,
            start_ms=start_ms,
            end_ms_exclusive=end_ms,
        )
        funding, funding_stats = fetch_funding(
            client,
            symbol=symbol,
            start_ms=start_ms,
            end_ms_exclusive=end_ms,
        )
        instrument, instrument_stats = fetch_instrument(client, symbol)
        bars_path = output / f"{symbol}_{args.interval}m.parquet"
        funding_path = output / f"{symbol}_funding.parquet"
        instrument_path = output / f"{symbol}_instrument.json"
        bars.to_parquet(bars_path, index=False, compression="zstd")
        funding.to_parquet(funding_path, index=False, compression="zstd")
        instrument_path.write_text(json.dumps(instrument, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        step_ms = int(args.interval) * 60_000
        expected_rows = math.ceil((end_ms - start_ms) / step_ms)
        missing_count = int(bars.attrs.get("missing_count", 0))
        manifest["symbols"][symbol] = {
            "bars": {
                "path": bars_path.name,
                "rows": int(len(bars)),
                "expected_rows": expected_rows,
                "missing_count": missing_count,
                "missing_first_utc": [utc_iso(value) for value in bars.attrs.get("missing_first", [])],
                "first_utc": utc_iso(int(bars["timestamp_ms"].iloc[0])),
                "last_utc": utc_iso(int(bars["timestamp_ms"].iloc[-1])),
                "sha256": sha256_file(bars_path),
                "fetch": bar_stats.__dict__,
            },
            "funding": {
                "path": funding_path.name,
                "rows": int(len(funding)),
                "first_utc": utc_iso(int(funding["timestamp_ms"].iloc[0])) if not funding.empty else None,
                "last_utc": utc_iso(int(funding["timestamp_ms"].iloc[-1])) if not funding.empty else None,
                "sha256": sha256_file(funding_path),
                "fetch": funding_stats.__dict__,
            },
            "instrument": {
                "path": instrument_path.name,
                "sha256": sha256_file(instrument_path),
                "fetch": instrument_stats.__dict__,
                "priceScale": instrument.get("priceScale"),
                "priceFilter": instrument.get("priceFilter"),
                "lotSizeFilter": instrument.get("lotSizeFilter"),
                "leverageFilter": instrument.get("leverageFilter"),
            },
        }
        print(
            f"{symbol}: bars={len(bars)}/{expected_rows} missing={missing_count} funding={len(funding)}",
            flush=True,
        )
    manifest_path = output / "DATA_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
