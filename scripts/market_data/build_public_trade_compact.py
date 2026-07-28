#!/usr/bin/env python3
"""Build one immutable monthly sparse 500 ms Bybit public-trade shard.

Only observed UTC-aligned 500 ms buckets are persisted. Covered no-trade
intervals and pre-listing/unavailable intervals are reconstructed from the
manifest by the paired loader, so no market information is discarded while
large all-zero grids and duplicate 1s/5s/15s files are avoided.
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

try:
    from . import build_public_trade_month as source
    from .canonical_spec import SYMBOLS, sha256_file
except ImportError:  # direct script execution
    import build_public_trade_month as source
    from canonical_spec import SYMBOLS, sha256_file

COMPACT_COLUMNS = (
    "start_time_ms",
    "open", "high", "low", "close",
    "buy_volume", "sell_volume", "buy_turnover", "sell_turnover",
    "trade_count",
    "first_offset_ms", "high_offset_ms", "low_offset_ms", "last_offset_ms",
    "available_at_ms",
)


class IncrementalCompactParquet:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.writer: pq.ParquetWriter | None = None
        self.rows = 0

    def append(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self.writer is None:
            self.writer = pq.ParquetWriter(
                self.path,
                table.schema,
                compression="zstd",
                compression_level=9,
                use_dictionary=True,
                write_statistics=True,
                version="2.6",
            )
        elif table.schema != self.writer.schema:
            table = table.cast(self.writer.schema)
        self.writer.write_table(table, row_group_size=min(len(frame), 500_000))
        self.rows += len(frame)

    def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            self.writer = None


def code_identity() -> dict[str, str | None]:
    repo = Path(__file__).resolve().parents[2]
    targets = {
        "compact_builder_sha256": repo / "scripts/market_data/build_public_trade_compact.py",
        "source_aggregator_sha256": repo / "scripts/market_data/build_public_trade_month.py",
        "loader_sha256": repo / "scripts/market_data/load_public_trade_compact.py",
        "verifier_sha256": repo / "scripts/market_data/verify_public_trade_compact.py",
        "contract_sha256": repo / "data/contracts/canonical_bybit_usdt_linear_v1.json",
    }
    return {name: sha256_file(path) if path.is_file() else None for name, path in targets.items()}


def compact_halfseconds(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame({
            "start_time_ms": pd.Series(dtype="int64"),
            "open": pd.Series(dtype="float64"),
            "high": pd.Series(dtype="float64"),
            "low": pd.Series(dtype="float64"),
            "close": pd.Series(dtype="float64"),
            "buy_volume": pd.Series(dtype="float64"),
            "sell_volume": pd.Series(dtype="float64"),
            "buy_turnover": pd.Series(dtype="float64"),
            "sell_turnover": pd.Series(dtype="float64"),
            "trade_count": pd.Series(dtype="int32"),
            "first_offset_ms": pd.Series(dtype="int16"),
            "high_offset_ms": pd.Series(dtype="int16"),
            "low_offset_ms": pd.Series(dtype="int16"),
            "last_offset_ms": pd.Series(dtype="int16"),
            "available_at_ms": pd.Series(dtype="int64"),
        })

    required = {
        "start_time_ms", "open", "high", "low", "close", "volume", "turnover",
        "buy_volume", "sell_volume", "buy_turnover", "sell_turnover", "trade_count",
        "first_offset_ms", "high_offset_ms", "low_offset_ms", "last_offset_ms",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"aggregated half-second columns missing: {sorted(missing)}")

    out = frame.copy()
    starts = pd.to_numeric(out["start_time_ms"], errors="raise").astype("int64")
    if (starts % 500 != 0).any() or starts.duplicated().any() or not starts.is_monotonic_increasing:
        raise ValueError("500 ms timestamps must be unique, increasing and UTC aligned")
    if not (
        (out["low"] <= out[["open", "close"]].min(axis=1)).all()
        and (out["high"] >= out[["open", "close"]].max(axis=1)).all()
    ):
        raise ValueError("500 ms OHLC ordering violation")
    flow = out[["volume", "turnover", "buy_volume", "sell_volume", "buy_turnover", "sell_turnover"]]
    if flow.isna().any().any() or (flow < 0).any().any():
        raise ValueError("invalid 500 ms flow values")
    volume_error = (out["buy_volume"] + out["sell_volume"] - out["volume"]).abs()
    turnover_error = (out["buy_turnover"] + out["sell_turnover"] - out["turnover"]).abs()
    if not (volume_error <= 1e-9 + out["volume"].abs() * 1e-10).all():
        raise ValueError("500 ms side volume does not reconcile")
    if not (turnover_error <= 1e-7 + out["turnover"].abs() * 1e-10).all():
        raise ValueError("500 ms side turnover does not reconcile")

    first = out["first_offset_ms"]
    high = out["high_offset_ms"]
    low = out["low_offset_ms"]
    last = out["last_offset_ms"]
    if not ((0 <= first) & (first <= high) & (high <= last) & (last <= 499)).all():
        raise ValueError("invalid high-event offset order")
    if not ((first <= low) & (low <= last)).all():
        raise ValueError("invalid low-event offset order")

    compact = pd.DataFrame({
        "start_time_ms": starts,
        "open": out["open"].astype("float64"),
        "high": out["high"].astype("float64"),
        "low": out["low"].astype("float64"),
        "close": out["close"].astype("float64"),
        "buy_volume": out["buy_volume"].astype("float64"),
        "sell_volume": out["sell_volume"].astype("float64"),
        "buy_turnover": out["buy_turnover"].astype("float64"),
        "sell_turnover": out["sell_turnover"].astype("float64"),
        "trade_count": out["trade_count"].astype("int32"),
        "first_offset_ms": out["first_offset_ms"].astype("int16"),
        "high_offset_ms": out["high_offset_ms"].astype("int16"),
        "low_offset_ms": out["low_offset_ms"].astype("int16"),
        "last_offset_ms": out["last_offset_ms"].astype("int16"),
        "available_at_ms": starts + 500,
    })
    return compact[list(COMPACT_COLUMNS)]


def _write_prelisting_manifest(
    output: Path,
    *,
    args: argparse.Namespace,
    start: datetime,
    end: datetime,
    span: source.RemoteSpan,
) -> Path:
    manifest = {
        "schema_version": 3,
        "dataset_id": f"DS-BYBIT-LINEAR-{args.symbol}-{args.month.replace('-', '')}-MICROBAR-SPARSE500-V3",
        "dataset_family_id": "DSF-BYBIT-LINEAR-4ASSET-MONTHLY-SPARSE500-V3",
        "claim_id": "CLM-20260727-CANONICAL-HALFYEAR-DATA-001",
        "provider": "Bybit official public archive",
        "source_kind": "daily_public_trades",
        "venue": "Bybit",
        "product": "USDT linear perpetual",
        "symbol": args.symbol,
        "month": args.month,
        "logical_segment": source.logical_segment(start),
        "start": start.isoformat().replace("+00:00", "Z"),
        "end_exclusive": end.isoformat().replace("+00:00", "Z"),
        "status": "PRELISTING",
        "archive_first_date": span.first_date.isoformat(),
        "archive_last_date": span.last_date.isoformat(),
        "stored_interval": "500ms_observed_sparse",
        "derived_intervals": ["1s", "5s", "15s"],
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
    start, end = source.month_bounds(args.month)
    segment = source.logical_segment(start)
    output = Path(args.out).resolve() / segment / args.symbol / args.month
    output.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "SMC_ICT_2_LIVE sparse 500ms builder/3"})
    span = source.discover_remote_span(session, args.symbol, args.timeout)
    if end.date() <= span.first_date:
        return _write_prelisting_manifest(output, args=args, start=start, end=end, span=span)
    if start.date() > span.last_date:
        raise RuntimeError(f"requested month begins after latest official archive date {span.last_date}")

    writer = IncrementalCompactParquet(output / "micro_bars" / "500ms_observed.parquet")
    sources: list[dict[str, Any]] = []
    unexpected_missing: list[str] = []
    leading_prelisting: list[str] = []
    raw_rows = raw_bytes = observed_halfseconds = 0

    try:
        with tempfile.TemporaryDirectory(prefix=f"bybit-sparse500-{args.symbol}-{args.month}-") as tmp:
            tmpdir = Path(tmp)
            for day in source.days(start, end):
                iso = day.isoformat()
                if day < span.first_date:
                    leading_prelisting.append(iso)
                    continue
                url = f"{source.BASE}/{args.symbol}/{args.symbol}{iso}.csv.gz"
                local = tmpdir / f"{args.symbol}{iso}.csv.gz"
                source_row = source.download_file(
                    session, url, local, timeout=args.timeout, max_attempts=args.max_attempts
                )
                source_row["date"] = iso
                if source_row.get("missing"):
                    unexpected_missing.append(iso)
                    sources.append(source_row)
                    continue
                halfsecond, rows = source.aggregate_trade_file(local, chunksize=args.chunksize)
                compact = compact_halfseconds(halfsecond)
                day_start_ms = int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)
                if not compact.empty and (
                    int(compact["start_time_ms"].iloc[0]) < day_start_ms
                    or int(compact["start_time_ms"].iloc[-1]) >= day_start_ms + 86_400_000
                ):
                    raise ValueError(f"trade timestamp outside source UTC day {iso}")
                writer.append(compact)
                source_row["rows"] = rows
                source_row["observed_halfseconds"] = int(len(compact))
                sources.append(source_row)
                raw_rows += rows
                raw_bytes += int(source_row.get("bytes", 0))
                observed_halfseconds += len(compact)
                local.unlink(missing_ok=True)
                print(json.dumps({"date": iso, "rows": rows, "observed_500ms": len(compact)}), flush=True)
    finally:
        writer.close()

    if unexpected_missing:
        raise RuntimeError(f"official source days missing on or after listing: {unexpected_missing}")
    if not writer.path.is_file():
        raise RuntimeError("no compact parquet was written for a listed month")

    files: list[dict[str, Any]] = [{
        "kind": "micro_bar",
        "name": "500ms_observed",
        "path": str(writer.path.relative_to(output)),
        "rows": writer.rows,
        "bytes": writer.path.stat().st_size,
        "sha256": sha256_file(writer.path),
    }]
    sources_path = output / "SOURCE_FILES.jsonl"
    sources_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in sources), encoding="utf-8")
    files.append({
        "kind": "source_audit",
        "name": "source_files",
        "path": sources_path.name,
        "rows": len(sources),
        "bytes": sources_path.stat().st_size,
        "sha256": sha256_file(sources_path),
    })

    manifest = {
        "schema_version": 3,
        "dataset_id": f"DS-BYBIT-LINEAR-{args.symbol}-{args.month.replace('-', '')}-MICROBAR-SPARSE500-V3",
        "dataset_family_id": "DSF-BYBIT-LINEAR-4ASSET-MONTHLY-SPARSE500-V3",
        "claim_id": "CLM-20260727-CANONICAL-HALFYEAR-DATA-001",
        "provider": "Bybit official public archive",
        "source_kind": "daily_public_trades_streamed_to_sparse_500ms",
        "source_base_url": source.BASE,
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
        "stored_interval": "500ms_observed_sparse",
        "derived_intervals": ["1s", "5s", "15s"],
        "sparse_semantics": (
            "A missing 500 ms row is a covered no-trade bucket when its UTC day is not listed in "
            "leading_prelisting_days or unexpected_missing_days; otherwise source_available is false."
        ),
        "causal_availability": (
            "Each observed 500 ms bucket is usable at start_time_ms+500; derived 1s/5s/15s bars "
            "are usable only at their interval close; no price carry is applied."
        ),
        "coverage": {
            "expected_days": calendar.monthrange(start.year, start.month)[1],
            "source_files_present": len([row for row in sources if not row.get("missing")]),
            "leading_prelisting_days": leading_prelisting,
            "unexpected_missing_days": unexpected_missing,
            "observed_500ms_rows": observed_halfseconds,
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
    output = build(parse_args())
    print(json.dumps({"status": "BUILT", "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
