from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

# Every hostname below is documented by Bybit as an official mainnet endpoint.
# We probe public market-data access and use the first endpoint that responds
# successfully. No authentication or geographic-identity evasion is attempted.
OFFICIAL_BASE_URLS: tuple[str, ...] = (
    "https://api.bybit.nl",
    "https://api.bybit.tr",
    "https://api.bybit.kz",
    "https://api.bybitgeorgia.ge",
    "https://api.bybit.ae",
    "https://api.bybit.id",
    "https://api.manepa.jp",
    "https://api.bybit.eu",
    "https://api.bybit.com",
    "https://api.bytick.com",
)


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def parse_utc(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class EndpointProbe:
    base_url: str
    ok: bool = False
    status_code: int | None = None
    ret_code: int | None = None
    ret_msg: str | None = None
    elapsed_seconds: float | None = None
    error: str | None = None


@dataclass
class FetchStats:
    endpoint: str
    symbol: str
    base_url: str
    pages: int = 0
    rows_raw: int = 0
    retries: int = 0
    request_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class BybitPublicClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: int = 30,
        min_interval: float = 0.075,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.min_interval = min_interval
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "SMC-ICT-causal-research/2.0",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.8",
                "Connection": "keep-alive",
            }
        )
        self._last_request = 0.0

    def get(self, endpoint: str, params: dict[str, Any], stats: FetchStats) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(8):
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            started = time.monotonic()
            try:
                self._last_request = time.monotonic()
                response = self.session.get(
                    f"{self.base_url}{endpoint}",
                    params=params,
                    timeout=self.timeout,
                )
                stats.request_seconds += time.monotonic() - started
                if response.status_code != 200:
                    raise RuntimeError(
                        f"HTTP {response.status_code}: {response.text[:300].replace(chr(10), ' ')}"
                    )
                payload = response.json()
                ret_code = int(payload.get("retCode", -1))
                if ret_code != 0:
                    raise RuntimeError(
                        f"Bybit retCode={ret_code} retMsg={payload.get('retMsg')}"
                    )
                return payload
            except Exception as exc:
                stats.request_seconds += max(0.0, time.monotonic() - started)
                stats.retries += 1
                last_error = exc
                message = f"attempt={attempt + 1} {type(exc).__name__}: {exc}"
                stats.errors.append(message[:500])
                time.sleep(min(8.0, (1.65**attempt) * 0.35 + random.random() * 0.2))
        raise RuntimeError(
            f"GET {self.base_url}{endpoint} failed after retries: {type(last_error).__name__}: {last_error}"
        )


def probe_endpoint(base_url: str, *, timeout: int = 18) -> EndpointProbe:
    probe = EndpointProbe(base_url=base_url)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "SMC-ICT-causal-research/2.0",
            "Accept": "application/json",
        }
    )
    started = time.monotonic()
    try:
        response = session.get(
            f"{base_url.rstrip('/')}/v5/market/kline",
            params={
                "category": "linear",
                "symbol": "BTCUSDT",
                "interval": "5",
                "limit": 2,
            },
            timeout=timeout,
        )
        probe.elapsed_seconds = round(time.monotonic() - started, 6)
        probe.status_code = int(response.status_code)
        if response.status_code != 200:
            probe.error = f"HTTP {response.status_code}: {response.text[:500].replace(chr(10), ' ')}"
            return probe
        payload = response.json()
        probe.ret_code = int(payload.get("retCode", -1))
        probe.ret_msg = str(payload.get("retMsg") or "")
        rows = payload.get("result", {}).get("list") or []
        probe.ok = probe.ret_code == 0 and bool(rows)
        if not probe.ok:
            probe.error = f"empty or nonzero response: retCode={probe.ret_code} retMsg={probe.ret_msg} rows={len(rows)}"
    except Exception as exc:
        probe.elapsed_seconds = round(time.monotonic() - started, 6)
        probe.error = f"{type(exc).__name__}: {exc}"
    return probe


def select_endpoint(output: Path) -> tuple[str, list[EndpointProbe]]:
    probes: list[EndpointProbe] = []
    for base_url in OFFICIAL_BASE_URLS:
        print(f"Probing official Bybit endpoint {base_url}", flush=True)
        probe = probe_endpoint(base_url)
        probes.append(probe)
        print(json.dumps(asdict(probe), ensure_ascii=False, sort_keys=True), flush=True)
        if probe.ok:
            path = output / "ENDPOINT_PROBE.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "probed_at": datetime.now(timezone.utc).isoformat(),
                        "selected": base_url,
                        "probes": [asdict(item) for item in probes],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            return base_url, probes
    path = output / "ENDPOINT_PROBE.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "probed_at": datetime.now(timezone.utc).isoformat(),
                "selected": None,
                "probes": [asdict(item) for item in probes],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    raise RuntimeError("No official Bybit mainnet endpoint returned public linear kline data")


def fetch_klines(
    client: BybitPublicClient,
    *,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms_exclusive: int,
) -> tuple[pd.DataFrame, FetchStats]:
    endpoint = "/v5/market/kline"
    stats = FetchStats(endpoint=endpoint, symbol=symbol, base_url=client.base_url)
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
        for column in ("open", "high", "low", "close", "volume", "turnover"):
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")
        frame = frame[
            (frame["timestamp_ms"] >= start_ms)
            & (frame["timestamp_ms"] < end_ms_exclusive)
        ]
        if not frame.empty:
            chunks.append(frame)
        oldest = min(int(row[0]) for row in rows)
        if seen_oldest is not None and oldest >= seen_oldest:
            raise RuntimeError(
                f"Kline pagination made no backward progress for {symbol}: oldest={oldest} prior={seen_oldest}"
            )
        seen_oldest = oldest
        if oldest <= start_ms:
            break
        cursor_end = oldest - 1
        if stats.pages % 50 == 0:
            print(
                f"{symbol} kline pages={stats.pages} rows={stats.rows_raw} "
                f"oldest={utc_iso(oldest)} retries={stats.retries}",
                flush=True,
            )
    if not chunks:
        raise RuntimeError(f"No kline data returned for {symbol}")
    data = pd.concat(chunks, ignore_index=True)
    data = (
        data.drop_duplicates("timestamp_ms", keep="last")
        .sort_values("timestamp_ms")
        .reset_index(drop=True)
    )
    expected = pd.RangeIndex(start_ms, end_ms_exclusive, step_ms)
    observed = pd.Index(data["timestamp_ms"].astype("int64"))
    missing = expected.difference(observed)
    data.attrs["missing_count"] = int(len(missing))
    data.attrs["missing_first"] = [int(value) for value in missing[:100]]
    return data, stats


def fetch_funding(
    client: BybitPublicClient,
    *,
    symbol: str,
    start_ms: int,
    end_ms_exclusive: int,
) -> tuple[pd.DataFrame, FetchStats]:
    endpoint = "/v5/market/funding/history"
    stats = FetchStats(endpoint=endpoint, symbol=symbol, base_url=client.base_url)
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
            timestamp = int(row["fundingRateTimestamp"])
            if start_ms <= timestamp < end_ms_exclusive:
                rows_out.append(
                    {
                        "timestamp_ms": timestamp,
                        "funding_rate": float(row["fundingRate"]),
                    }
                )
        oldest = min(int(row["fundingRateTimestamp"]) for row in rows)
        if seen_oldest is not None and oldest >= seen_oldest:
            raise RuntimeError(
                f"Funding pagination made no backward progress for {symbol}: oldest={oldest} prior={seen_oldest}"
            )
        seen_oldest = oldest
        if oldest <= start_ms:
            break
        cursor_end = oldest - 1
    data = pd.DataFrame(rows_out, columns=["timestamp_ms", "funding_rate"])
    if not data.empty:
        data = (
            data.drop_duplicates("timestamp_ms", keep="last")
            .sort_values("timestamp_ms")
            .reset_index(drop=True)
        )
    return data, stats


def fetch_instrument(
    client: BybitPublicClient,
    symbol: str,
) -> tuple[dict[str, Any], FetchStats]:
    endpoint = "/v5/market/instruments-info"
    stats = FetchStats(endpoint=endpoint, symbol=symbol, base_url=client.base_url)
    payload = client.get(
        endpoint,
        {"category": "linear", "symbol": symbol},
        stats,
    )
    rows = payload.get("result", {}).get("list") or []
    if not rows:
        raise RuntimeError(f"No instrument info returned for {symbol}")
    return rows[0], stats


def self_test() -> None:
    assert parse_utc("2024-01-01T00:00:00Z") == 1704067200000
    assert utc_iso(1704067200000).startswith("2024-01-01T00:00:00")
    expected = pd.RangeIndex(0, 900_000, 300_000)
    observed = pd.Index([0, 300_000, 600_000])
    assert len(expected.difference(observed)) == 0
    assert len(OFFICIAL_BASE_URLS) >= 8
    print("self-test: ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download causal Bybit linear-perpetual research bars through an official reachable endpoint."
    )
    parser.add_argument("--output", type=Path, default=Path("artifact/bybit_data_v2"))
    parser.add_argument("--start", default="2021-01-01T00:00:00Z")
    parser.add_argument("--end-exclusive", default="2026-07-01T00:00:00Z")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--interval", default="5")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    try:
        selected_base_url, probes = select_endpoint(output)
        if args.probe_only:
            print(f"selected official endpoint: {selected_base_url}")
            return 0
        start_ms = parse_utc(args.start)
        end_ms = parse_utc(args.end_exclusive)
        if start_ms >= end_ms:
            raise ValueError("start must be before end-exclusive")
        client = BybitPublicClient(selected_base_url)
        manifest: dict[str, Any] = {
            "schema_version": 2,
            "source": "Bybit V5 public market API",
            "official_base_url": selected_base_url,
            "endpoint_probes": [asdict(item) for item in probes],
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
            print(
                f"Downloading {symbol} {args.interval}m {args.start} -> {args.end_exclusive} via {selected_base_url}",
                flush=True,
            )
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
            instrument_path.write_text(
                json.dumps(instrument, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            expected_rows = math.ceil(
                (end_ms - start_ms) / (int(args.interval) * 60_000)
            )
            missing_count = int(bars.attrs.get("missing_count", 0))
            manifest["symbols"][symbol] = {
                "bars": {
                    "path": bars_path.name,
                    "rows": int(len(bars)),
                    "expected_rows": expected_rows,
                    "missing_count": missing_count,
                    "missing_first_utc": [
                        utc_iso(value) for value in bars.attrs.get("missing_first", [])
                    ],
                    "first_utc": utc_iso(int(bars["timestamp_ms"].iloc[0])),
                    "last_utc": utc_iso(int(bars["timestamp_ms"].iloc[-1])),
                    "sha256": sha256_file(bars_path),
                    "fetch": asdict(bar_stats),
                },
                "funding": {
                    "path": funding_path.name,
                    "rows": int(len(funding)),
                    "first_utc": (
                        utc_iso(int(funding["timestamp_ms"].iloc[0]))
                        if not funding.empty
                        else None
                    ),
                    "last_utc": (
                        utc_iso(int(funding["timestamp_ms"].iloc[-1]))
                        if not funding.empty
                        else None
                    ),
                    "sha256": sha256_file(funding_path),
                    "fetch": asdict(funding_stats),
                },
                "instrument": {
                    "path": instrument_path.name,
                    "sha256": sha256_file(instrument_path),
                    "fetch": asdict(instrument_stats),
                    "priceScale": instrument.get("priceScale"),
                    "priceFilter": instrument.get("priceFilter"),
                    "lotSizeFilter": instrument.get("lotSizeFilter"),
                    "leverageFilter": instrument.get("leverageFilter"),
                },
            }
            print(
                f"{symbol}: bars={len(bars)}/{expected_rows} missing={missing_count} "
                f"funding={len(funding)}",
                flush=True,
            )
        manifest_path = output / "DATA_MANIFEST.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        failure = {
            "schema_version": 1,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        (output / "DATA_FAILURE.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
