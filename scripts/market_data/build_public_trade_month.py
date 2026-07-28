#!/usr/bin/env python3
"""Build one immutable monthly Bybit microbar shard from official public trades.

The one-second table contains standard 1s OHLC/flow plus two exact UTC-aligned
500 ms halves. Five-second and fifteen-second bars are stored separately. Daily
source archives are SHA-256 identified, processed once and removed afterwards.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

try:
    from .canonical_spec import SYMBOLS, sha256_file
except ImportError:
    from canonical_spec import SYMBOLS, sha256_file

BASE = "https://public.bybit.com/trading"
FIRST_MONTH = datetime(2021, 1, 1, tzinfo=timezone.utc)
END_EXCLUSIVE = datetime(2026, 7, 1, tzinfo=timezone.utc)
PRICE_COLUMNS = ("open", "high", "low", "close")
FLOW_COLUMNS = (
    "volume", "turnover", "trade_count", "buy_volume", "sell_volume",
    "buy_turnover", "sell_turnover",
)
HALF_VALUE_COLUMNS = (*PRICE_COLUMNS, *FLOW_COLUMNS)
HALF_OFFSET_COLUMNS = ("first_offset_ms", "high_offset_ms", "low_offset_ms", "last_offset_ms")


@dataclass
class RemoteSpan:
    first_date: date
    last_date: date
    file_count: int


def month_bounds(month: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    if start < FIRST_MONTH or start >= END_EXCLUSIVE:
        raise ValueError("month must be between 2021-01 and 2026-06")
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end


def logical_segment(start: datetime) -> str:
    if start < datetime(2024, 1, 1, tzinfo=timezone.utc):
        return "PRE_2024"
    if start < datetime(2024, 7, 1, tzinfo=timezone.utc):
        return "2024_H1"
    if start < datetime(2025, 1, 1, tzinfo=timezone.utc):
        return "2024_H2"
    if start < datetime(2025, 7, 1, tzinfo=timezone.utc):
        return "2025_H1"
    if start < datetime(2026, 1, 1, tzinfo=timezone.utc):
        return "2025_H2"
    return "2026_H1"


def days(start: datetime, end: datetime) -> Iterable[date]:
    current = start.date()
    while current < end.date():
        yield current
        current += timedelta(days=1)


def code_identity() -> dict[str, str | None]:
    repo = Path(__file__).resolve().parents[2]
    targets = {
        "builder_sha256": repo / "scripts/market_data/build_public_trade_month.py",
        "segment_builder_sha256": repo / "scripts/market_data/build_public_trade_segment.py",
        "loader_sha256": repo / "scripts/market_data/load_canonical_bybit.py",
        "verifier_sha256": repo / "scripts/market_data/verify_canonical_bybit.py",
        "spec_sha256": repo / "scripts/market_data/canonical_spec.py",
        "contract_sha256": repo / "data/contracts/canonical_bybit_usdt_linear_v1.json",
    }
    return {name: sha256_file(path) if path.is_file() else None for name, path in targets.items()}


def discover_remote_span(session: requests.Session, symbol: str, timeout: int) -> RemoteSpan:
    response = session.get(f"{BASE}/{symbol}/", timeout=timeout)
    response.raise_for_status()
    pattern = re.compile(rf'{re.escape(symbol)}(\d{{4}}-\d{{2}}-\d{{2}})\.csv\.gz')
    found = sorted({date.fromisoformat(value) for value in pattern.findall(response.text)})
    if not found:
        raise RuntimeError(f"official archive directory contains no files for {symbol}")
    return RemoteSpan(first_date=found[0], last_date=found[-1], file_count=len(found))


def download_file(
    session: requests.Session,
    url: str,
    path: Path,
    *,
    timeout: int,
    max_attempts: int,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        digest = hashlib.sha256()
        total = 0
        try:
            with session.get(url, timeout=timeout, stream=True) as response:
                if response.status_code == 404:
                    return {"url": url, "status": 404, "missing": True}
                response.raise_for_status()
                with path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        if not chunk:
                            continue
                        digest.update(chunk)
                        total += len(chunk)
                        handle.write(chunk)
                return {
                    "url": url,
                    "status": response.status_code,
                    "missing": False,
                    "bytes": total,
                    "sha256": digest.hexdigest(),
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "content_type": response.headers.get("Content-Type"),
                }
        except (requests.RequestException, OSError) as exc:
            last_error = exc
            path.unlink(missing_ok=True)
            if attempt < max_attempts:
                time.sleep(min(60.0, 1.5 * (2 ** (attempt - 1))))
    raise RuntimeError(f"failed after {max_attempts} attempts: {url}: {last_error}")


def _chunk_to_halfsecond(chunk: pd.DataFrame, path: Path) -> pd.DataFrame:
    required = ["timestamp", "side", "size", "price"]
    if chunk[required].isna().any().any():
        raise ValueError(f"null source value in {path}")
    side = chunk["side"].astype("string").str.casefold()
    if not side.isin(["buy", "sell"]).all():
        invalid = sorted(set(side[~side.isin(["buy", "sell"])].dropna().tolist()))
        raise ValueError(f"unsupported trade side in {path}: {invalid[:10]}")

    timestamp_ms = np.floor(chunk["timestamp"].to_numpy(dtype="float64") * 1000.0 + 1e-7).astype("int64")
    if len(timestamp_ms) > 1 and np.any(np.diff(timestamp_ms) < 0):
        raise ValueError(f"source timestamps are not nondecreasing in {path}")
    bucket = (timestamp_ms // 500) * 500
    offset = (timestamp_ms - bucket).astype("int16")
    size = chunk["size"].to_numpy(dtype="float64")
    price = chunk["price"].to_numpy(dtype="float64")
    turnover = size * price
    buy = side.eq("buy").to_numpy()
    enriched = pd.DataFrame({
        "start_time_ms": bucket,
        "price": price,
        "size": size,
        "turnover": turnover,
        "buy_volume": np.where(buy, size, 0.0),
        "sell_volume": np.where(~buy, size, 0.0),
        "buy_turnover": np.where(buy, turnover, 0.0),
        "sell_turnover": np.where(~buy, turnover, 0.0),
        "offset_ms": offset,
    })
    grouped = enriched.groupby("start_time_ms", sort=True, observed=True)
    out = grouped.agg(
        open=("price", "first"), high=("price", "max"), low=("price", "min"), close=("price", "last"),
        volume=("size", "sum"), turnover=("turnover", "sum"), trade_count=("price", "size"),
        buy_volume=("buy_volume", "sum"), sell_volume=("sell_volume", "sum"),
        buy_turnover=("buy_turnover", "sum"), sell_turnover=("sell_turnover", "sum"),
        first_offset_ms=("offset_ms", "first"), last_offset_ms=("offset_ms", "last"),
    )
    high_rows = enriched.loc[grouped["price"].idxmax(), ["start_time_ms", "offset_ms"]]
    low_rows = enriched.loc[grouped["price"].idxmin(), ["start_time_ms", "offset_ms"]]
    out["high_offset_ms"] = high_rows.set_index("start_time_ms")["offset_ms"]
    out["low_offset_ms"] = low_rows.set_index("start_time_ms")["offset_ms"]
    return out.reset_index()


def aggregate_trade_file(path: Path, *, chunksize: int) -> tuple[pd.DataFrame, int]:
    parts: list[pd.DataFrame] = []
    total_rows = 0
    last_timestamp_ms: int | None = None
    reader = pd.read_csv(
        path,
        compression="gzip",
        usecols=["timestamp", "side", "size", "price"],
        dtype={"timestamp": "float64", "side": "string", "size": "float64", "price": "float64"},
        chunksize=chunksize,
        on_bad_lines="error",
    )
    for chunk in reader:
        if chunk.empty:
            continue
        timestamps = np.floor(chunk["timestamp"].to_numpy(dtype="float64") * 1000.0 + 1e-7).astype("int64")
        if last_timestamp_ms is not None and int(timestamps[0]) < last_timestamp_ms:
            raise ValueError(f"source timestamps regress across chunks in {path}")
        last_timestamp_ms = int(timestamps[-1])
        total_rows += len(chunk)
        parts.append(_chunk_to_halfsecond(chunk, path))
    if not parts:
        return pd.DataFrame(columns=["start_time_ms", *HALF_VALUE_COLUMNS, *HALF_OFFSET_COLUMNS]), total_rows

    partial = pd.concat(parts, ignore_index=True)
    grouped = partial.groupby("start_time_ms", sort=True, observed=True)
    daily = grouped.agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), turnover=("turnover", "sum"), trade_count=("trade_count", "sum"),
        buy_volume=("buy_volume", "sum"), sell_volume=("sell_volume", "sum"),
        buy_turnover=("buy_turnover", "sum"), sell_turnover=("sell_turnover", "sum"),
        first_offset_ms=("first_offset_ms", "min"), last_offset_ms=("last_offset_ms", "max"),
    )
    max_high = grouped["high"].transform("max")
    min_low = grouped["low"].transform("min")
    daily["high_offset_ms"] = (
        partial.loc[partial["high"].eq(max_high)]
        .groupby("start_time_ms", sort=True)["high_offset_ms"].min()
    )
    daily["low_offset_ms"] = (
        partial.loc[partial["low"].eq(min_low)]
        .groupby("start_time_ms", sort=True)["low_offset_ms"].min()
    )
    return daily.reset_index(), total_rows


def _half_frame(
    halfsecond: pd.DataFrame,
    second_index: pd.Index,
    *,
    half: int,
    source_available: bool,
) -> pd.DataFrame:
    prefix = f"h{half}_"
    offset = half * 500
    if source_available and not halfsecond.empty:
        selected = halfsecond[halfsecond["start_time_ms"] % 1000 == offset].copy()
        selected["start_time_ms"] = selected["start_time_ms"] - offset
        selected = selected.set_index("start_time_ms")
    else:
        selected = pd.DataFrame(index=pd.Index([], dtype="int64", name="start_time_ms"))
    selected = selected.reindex(second_index)
    out = pd.DataFrame(index=second_index)
    observed = selected["open"].notna() if "open" in selected else pd.Series(False, index=second_index)
    out[prefix + "observed"] = observed.astype(bool)
    for column in PRICE_COLUMNS:
        out[prefix + column] = selected[column].astype("float64") if column in selected else np.nan
    for column in ("volume", "turnover", "buy_volume", "sell_volume", "buy_turnover", "sell_turnover"):
        if source_available:
            out[prefix + column] = selected[column].fillna(0.0).astype("float64") if column in selected else 0.0
        else:
            out[prefix + column] = np.nan
    if source_available:
        out[prefix + "trade_count"] = selected["trade_count"].fillna(0).astype("int32") if "trade_count" in selected else 0
        for name in HALF_OFFSET_COLUMNS:
            out[prefix + name] = selected[name].fillna(-1).astype("int16") if name in selected else -1
    else:
        out[prefix + "trade_count"] = np.full(len(out), -1, dtype="int32")
        for name in HALF_OFFSET_COLUMNS:
            out[prefix + name] = np.full(len(out), -1, dtype="int16")
    out[prefix + "available_at_ms"] = second_index.to_numpy(dtype="int64") + offset + 500
    return out


def build_one_second_day(halfsecond: pd.DataFrame, day: date, *, source_available: bool) -> pd.DataFrame:
    start_ms = int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)
    second_index = pd.Index(range(start_ms, start_ms + 86_400_000, 1_000), dtype="int64", name="start_time_ms")
    h0 = _half_frame(halfsecond, second_index, half=0, source_available=source_available)
    h1 = _half_frame(halfsecond, second_index, half=1, source_available=source_available)
    out = pd.concat([h0, h1], axis=1)
    out.insert(0, "source_available", bool(source_available))
    out.insert(0, "start_time_ms", second_index.to_numpy(dtype="int64"))
    out["observed"] = out["h0_observed"] | out["h1_observed"]
    out["open"] = out["h0_open"].combine_first(out["h1_open"])
    out["high"] = out[["h0_high", "h1_high"]].max(axis=1, skipna=True)
    out["low"] = out[["h0_low", "h1_low"]].min(axis=1, skipna=True)
    out["close"] = out["h1_close"].combine_first(out["h0_close"])
    for column in ("volume", "turnover", "buy_volume", "sell_volume", "buy_turnover", "sell_turnover"):
        out[column] = out[f"h0_{column}"] + out[f"h1_{column}"] if source_available else np.nan
    if source_available:
        out["trade_count"] = (out["h0_trade_count"] + out["h1_trade_count"]).astype("int32")
    else:
        out["trade_count"] = np.full(len(out), -1, dtype="int32")
    out["available_at_ms"] = out["start_time_ms"] + 1_000
    ordered = ["start_time_ms", "source_available", "observed", *PRICE_COLUMNS, *FLOW_COLUMNS, "available_at_ms"]
    for half in ("h0", "h1"):
        ordered.extend([
            f"{half}_observed", *[f"{half}_{column}" for column in HALF_VALUE_COLUMNS],
            *[f"{half}_{name}" for name in HALF_OFFSET_COLUMNS], f"{half}_available_at_ms",
        ])
    return out[ordered].reset_index(drop=True)


def derive_seconds(one_second: pd.DataFrame, interval_seconds: int) -> pd.DataFrame:
    if interval_seconds not in {5, 15}:
        raise ValueError("interval_seconds must be 5 or 15")
    interval_ms = interval_seconds * 1_000
    temp = one_second.copy()
    temp["bucket_ms"] = (temp["start_time_ms"] // interval_ms) * interval_ms
    grouped = temp.groupby("bucket_ms", sort=True, observed=True)
    out = pd.DataFrame({
        "start_time_ms": grouped["start_time_ms"].first(),
        "source_available": grouped["source_available"].all(),
        "observed": grouped["observed"].any(),
        "open": grouped["open"].first(), "high": grouped["high"].max(),
        "low": grouped["low"].min(), "close": grouped["close"].last(),
        "volume": grouped["volume"].sum(min_count=1),
        "turnover": grouped["turnover"].sum(min_count=1),
        "trade_count": grouped["trade_count"].sum(min_count=1),
        "buy_volume": grouped["buy_volume"].sum(min_count=1),
        "sell_volume": grouped["sell_volume"].sum(min_count=1),
        "buy_turnover": grouped["buy_turnover"].sum(min_count=1),
        "sell_turnover": grouped["sell_turnover"].sum(min_count=1),
        "source_seconds_available": grouped["source_available"].sum(),
        "source_seconds_total": grouped["source_available"].size(),
        "observed_seconds": grouped["observed"].sum(),
    }).reset_index(drop=True)
    out["available_at_ms"] = out["start_time_ms"] + interval_ms
    invalid = ~out["source_available"]
    out.loc[invalid, [*PRICE_COLUMNS, *FLOW_COLUMNS]] = np.nan
    out["trade_count"] = out["trade_count"].fillna(-1).astype("int32")
    out["source_seconds_available"] = out["source_seconds_available"].astype("int16")
    out["source_seconds_total"] = out["source_seconds_total"].astype("int16")
    out["observed_seconds"] = out["observed_seconds"].astype("int16")
    return out


def numeric_sanity(one_second: pd.DataFrame) -> None:
    available = one_second[one_second["source_available"]]
    observed = available[available["observed"]]
    if observed.empty:
        raise ValueError("available day has no observed trades")
    if not (
        (observed["low"] <= observed[["open", "close"]].min(axis=1)).all()
        and (observed["high"] >= observed[["open", "close"]].max(axis=1)).all()
    ):
        raise ValueError("OHLC ordering violation")
    if (available[["volume", "turnover", "trade_count", "buy_volume", "sell_volume"]] < 0).any().any():
        raise ValueError("negative one-second aggregate")
    imbalance = (available["buy_volume"] + available["sell_volume"] - available["volume"]).abs()
    tolerance = 1e-9 + available["volume"].abs() * 1e-10
    if not (imbalance <= tolerance).all():
        raise ValueError("buy/sell volume does not reconcile to total volume")
    for half in ("h0", "h1"):
        active = available[available[f"{half}_observed"]]
        if active.empty:
            continue
        first = active[f"{half}_first_offset_ms"]
        high = active[f"{half}_high_offset_ms"]
        low = active[f"{half}_low_offset_ms"]
        last = active[f"{half}_last_offset_ms"]
        if not ((0 <= first) & (first <= high) & (high <= last) & (last <= 499)).all():
            raise ValueError(f"invalid {half} high offsets")
        if not ((first <= low) & (low <= last)).all():
            raise ValueError(f"invalid {half} low offsets")


class IncrementalParquet:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.writer: pq.ParquetWriter | None = None
        self.rows = 0

    def append(self, frame: pd.DataFrame) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self.writer is None:
            self.writer = pq.ParquetWriter(
                self.path, table.schema, compression="zstd", compression_level=9,
                use_dictionary=True, write_statistics=True, version="2.6",
            )
        self.writer.write_table(table, row_group_size=min(len(frame), 250_000))
        self.rows += len(frame)

    def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            self.writer = None


def _write_prelisting_manifest(
    output: Path,
    *,
    args: argparse.Namespace,
    start: datetime,
    end: datetime,
    span: RemoteSpan,
) -> Path:
    manifest = {
        "schema_version": 2,
        "dataset_id": f"DS-BYBIT-LINEAR-{args.symbol}-{args.month.replace('-', '')}-MICROBAR-V2",
        "dataset_family_id": "DSF-BYBIT-LINEAR-4ASSET-MONTHLY-MICROBAR-V2",
        "claim_id": "CLM-20260727-CANONICAL-HALFYEAR-DATA-001",
        "provider": "Bybit official public archive",
        "source_kind": "daily_public_trades",
        "venue": "Bybit",
        "product": "USDT linear perpetual",
        "symbol": args.symbol,
        "month": args.month,
        "logical_segment": logical_segment(start),
        "start": start.isoformat().replace("+00:00", "Z"),
        "end_exclusive": end.isoformat().replace("+00:00", "Z"),
        "status": "PRELISTING",
        "archive_first_date": span.first_date.isoformat(),
        "archive_last_date": span.last_date.isoformat(),
        "files": [],
        "credentials_used": False,
        "orders_submitted": False,
    }
    path = output / "DATASET_MANIFEST.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "DATASET_MANIFEST.sha256").write_text(f"{sha256_file(path)}  {path.name}\n", encoding="utf-8")
    return output


def build(args: argparse.Namespace) -> Path:
    if args.symbol not in SYMBOLS:
        raise ValueError(f"unsupported symbol {args.symbol}")
    start, end = month_bounds(args.month)
    segment = logical_segment(start)
    output = Path(args.out).resolve() / segment / args.symbol / args.month
    output.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "SMC_ICT_2_LIVE canonical microbar builder/2"})
    span = discover_remote_span(session, args.symbol, args.timeout)
    if end.date() <= span.first_date:
        return _write_prelisting_manifest(output, args=args, start=start, end=end, span=span)
    if start.date() > span.last_date:
        raise RuntimeError(f"requested month begins after latest official archive date {span.last_date}")

    writers = {
        "1s": IncrementalParquet(output / "micro_bars" / "1s.parquet"),
        "5s": IncrementalParquet(output / "micro_bars" / "5s.parquet"),
        "15s": IncrementalParquet(output / "micro_bars" / "15s.parquet"),
    }
    sources: list[dict[str, Any]] = []
    unexpected_missing: list[str] = []
    leading_prelisting: list[str] = []
    source_seconds_available = observed_seconds = raw_rows = raw_bytes = 0

    try:
        with tempfile.TemporaryDirectory(prefix=f"bybit-micro-{args.symbol}-{args.month}-") as tmp:
            tmpdir = Path(tmp)
            for day in days(start, end):
                iso = day.isoformat()
                if day < span.first_date:
                    leading_prelisting.append(iso)
                    one_second = build_one_second_day(pd.DataFrame(), day, source_available=False)
                else:
                    url = f"{BASE}/{args.symbol}/{args.symbol}{iso}.csv.gz"
                    local = tmpdir / f"{args.symbol}{iso}.csv.gz"
                    source = download_file(session, url, local, timeout=args.timeout, max_attempts=args.max_attempts)
                    source["date"] = iso
                    if source.get("missing"):
                        unexpected_missing.append(iso)
                        sources.append(source)
                        continue
                    halfsecond, rows = aggregate_trade_file(local, chunksize=args.chunksize)
                    source["rows"] = rows
                    source["observed_halfseconds"] = int(len(halfsecond))
                    sources.append(source)
                    raw_rows += rows
                    raw_bytes += int(source.get("bytes", 0))
                    one_second = build_one_second_day(halfsecond, day, source_available=True)
                    numeric_sanity(one_second)
                    source_seconds_available += int(one_second["source_available"].sum())
                    observed_seconds += int(one_second["observed"].sum())
                    local.unlink(missing_ok=True)
                    print(json.dumps({"date": iso, "rows": rows, "halfseconds": len(halfsecond)}), flush=True)
                writers["1s"].append(one_second)
                writers["5s"].append(derive_seconds(one_second, 5))
                writers["15s"].append(derive_seconds(one_second, 15))
    finally:
        for writer in writers.values():
            writer.close()

    if unexpected_missing:
        raise RuntimeError(f"official source days missing on or after listing: {unexpected_missing}")

    files: list[dict[str, Any]] = []
    for name, writer in writers.items():
        path = writer.path
        if not path.is_file():
            raise RuntimeError(f"expected output not written: {path}")
        files.append({
            "kind": "micro_bar", "name": name, "path": str(path.relative_to(output)),
            "rows": writer.rows, "bytes": path.stat().st_size, "sha256": sha256_file(path),
        })
    sources_path = output / "SOURCE_FILES.jsonl"
    sources_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in sources), encoding="utf-8")
    files.append({
        "kind": "source_audit", "name": "source_files", "path": sources_path.name,
        "rows": len(sources), "bytes": sources_path.stat().st_size, "sha256": sha256_file(sources_path),
    })

    manifest = {
        "schema_version": 2,
        "dataset_id": f"DS-BYBIT-LINEAR-{args.symbol}-{args.month.replace('-', '')}-MICROBAR-V2",
        "dataset_family_id": "DSF-BYBIT-LINEAR-4ASSET-MONTHLY-MICROBAR-V2",
        "claim_id": "CLM-20260727-CANONICAL-HALFYEAR-DATA-001",
        "provider": "Bybit official public archive",
        "source_kind": "daily_public_trades_streamed_to_microbars",
        "source_base_url": BASE,
        "venue": "Bybit",
        "product": "USDT linear perpetual",
        "symbol": args.symbol,
        "month": args.month,
        "logical_segment": segment,
        "start": start.isoformat().replace("+00:00", "Z"),
        "end_exclusive": end.isoformat().replace("+00:00", "Z"),
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "code_identity": code_identity(),
        "status": "VERIFIED",
        "archive_first_date": span.first_date.isoformat(),
        "archive_last_date": span.last_date.isoformat(),
        "archive_directory_file_count": span.file_count,
        "stored_intervals": ["1s", "5s", "15s"],
        "derived_interval": "500ms",
        "five_hundred_ms_storage": "Each 1s row stores h0 and h1 UTC-aligned 500 ms OHLC/flow, first/high/low/last event offsets and separate availability timestamps.",
        "causal_availability": "h0 at second+500ms; h1 and completed 1s at second+1000ms; 5s and 15s at interval close; no price carry across no-trade intervals.",
        "coverage": {
            "expected_days": calendar.monthrange(start.year, start.month)[1],
            "source_files_present": len(sources),
            "leading_prelisting_days": leading_prelisting,
            "unexpected_missing_days": unexpected_missing,
            "source_seconds_available": source_seconds_available,
            "observed_trade_seconds": observed_seconds,
        },
        "files": files,
        "source_file_count": len(sources),
        "source_raw_bytes": raw_bytes,
        "source_raw_rows": raw_rows,
        "source_raw_files_deleted_after_processing": True,
        "credentials_used": False,
        "orders_submitted": False,
    }
    manifest_path = output / "DATASET_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "DATASET_MANIFEST.sha256").write_text(
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n", encoding="utf-8"
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, choices=SYMBOLS)
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--chunksize", type=int, default=750_000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = build(args)
    print(json.dumps({"status": "BUILT", "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
