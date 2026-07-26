#!/usr/bin/env python3
"""Build one immutable monthly Bybit USDT-linear trade-flow bar shard.

The source is Bybit's official public daily trade archive. Each compressed file
is downloaded once, SHA-256 identified, streamed through chunked aggregation,
and deleted after its 1-minute contribution is incorporated. Missing minutes
remain explicit. Higher bars are derived only from complete 1-minute groups.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests

try:
    from .canonical_spec import sha256_file, write_parquet
except ImportError:  # direct script execution
    from canonical_spec import sha256_file, write_parquet

BASE = "https://public.bybit.com/trading"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
BAR_RULES = {
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}
FLOW_COLUMNS = (
    "volume",
    "turnover",
    "trade_count",
    "buy_volume",
    "sell_volume",
    "buy_turnover",
    "sell_turnover",
)


@dataclass
class MinuteAccumulator:
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float
    trade_count: int
    buy_volume: float
    sell_volume: float
    buy_turnover: float
    sell_turnover: float

    def merge(self, row: pd.Series) -> None:
        self.high = max(self.high, float(row["high"]))
        self.low = min(self.low, float(row["low"]))
        self.close = float(row["close"])
        self.volume += float(row["volume"])
        self.turnover += float(row["turnover"])
        self.trade_count += int(row["trade_count"])
        self.buy_volume += float(row["buy_volume"])
        self.sell_volume += float(row["sell_volume"])
        self.buy_turnover += float(row["buy_turnover"])
        self.sell_turnover += float(row["sell_turnover"])


def month_bounds(month: str) -> tuple[datetime, datetime]:
    parsed = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    if parsed.year < 2020 or parsed >= datetime(2026, 7, 1, tzinfo=timezone.utc):
        raise ValueError("month must be between 2020-01 and 2026-06")
    if parsed.month == 12:
        end = parsed.replace(year=parsed.year + 1, month=1)
    else:
        end = parsed.replace(month=parsed.month + 1)
    return parsed, end


def logical_segment(month_start: datetime) -> str:
    if month_start < datetime(2024, 1, 1, tzinfo=timezone.utc):
        return "PRE_2024"
    if month_start < datetime(2024, 7, 1, tzinfo=timezone.utc):
        return "2024_H1"
    if month_start < datetime(2025, 1, 1, tzinfo=timezone.utc):
        return "2024_H2"
    if month_start < datetime(2025, 7, 1, tzinfo=timezone.utc):
        return "2025_H1"
    if month_start < datetime(2026, 1, 1, tzinfo=timezone.utc):
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
        "spec_sha256": repo / "scripts/market_data/canonical_spec.py",
        "loader_sha256": repo / "scripts/market_data/load_canonical_bybit.py",
        "verifier_sha256": repo / "scripts/market_data/verify_canonical_bybit.py",
        "contract_sha256": repo / "data/contracts/canonical_bybit_usdt_linear_v1.json",
    }
    return {name: sha256_file(path) if path.is_file() else None for name, path in targets.items()}


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
            if attempt == max_attempts:
                break
            time.sleep(min(60.0, 1.5 * (2 ** (attempt - 1))))
    raise RuntimeError(f"failed after {max_attempts} attempts: {url}: {last_error}")


def aggregate_trade_file(path: Path, *, chunksize: int) -> tuple[dict[int, MinuteAccumulator], int]:
    accumulators: dict[int, MinuteAccumulator] = {}
    total_rows = 0
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
        total_rows += len(chunk)
        if chunk[["timestamp", "size", "price"]].isna().any().any():
            raise ValueError(f"null numeric source value in {path}")
        timestamp_ms = np.floor(chunk["timestamp"].to_numpy(dtype="float64") * 1000.0).astype("int64")
        chunk = chunk.assign(
            start_time_ms=(timestamp_ms // 60_000) * 60_000,
            turnover=chunk["size"].to_numpy() * chunk["price"].to_numpy(),
            buy_volume=np.where(chunk["side"].str.casefold().eq("buy"), chunk["size"], 0.0),
            sell_volume=np.where(chunk["side"].str.casefold().eq("sell"), chunk["size"], 0.0),
        )
        chunk["buy_turnover"] = np.where(
            chunk["side"].str.casefold().eq("buy"), chunk["turnover"], 0.0
        )
        chunk["sell_turnover"] = np.where(
            chunk["side"].str.casefold().eq("sell"), chunk["turnover"], 0.0
        )
        grouped = chunk.groupby("start_time_ms", sort=True, observed=True).agg(
            open=("price", "first"),
            high=("price", "max"),
            low=("price", "min"),
            close=("price", "last"),
            volume=("size", "sum"),
            turnover=("turnover", "sum"),
            trade_count=("price", "size"),
            buy_volume=("buy_volume", "sum"),
            sell_volume=("sell_volume", "sum"),
            buy_turnover=("buy_turnover", "sum"),
            sell_turnover=("sell_turnover", "sum"),
        )
        for minute, row in grouped.iterrows():
            minute_i = int(minute)
            if minute_i not in accumulators:
                accumulators[minute_i] = MinuteAccumulator(
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    turnover=float(row["turnover"]),
                    trade_count=int(row["trade_count"]),
                    buy_volume=float(row["buy_volume"]),
                    sell_volume=float(row["sell_volume"]),
                    buy_turnover=float(row["buy_turnover"]),
                    sell_turnover=float(row["sell_turnover"]),
                )
            else:
                accumulators[minute_i].merge(row)
    return accumulators, total_rows


def merge_accumulators(
    target: dict[int, MinuteAccumulator], source: dict[int, MinuteAccumulator]
) -> None:
    for minute in sorted(source):
        row = source[minute]
        if minute not in target:
            target[minute] = row
            continue
        synthetic = pd.Series({
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
            "turnover": row.turnover,
            "trade_count": row.trade_count,
            "buy_volume": row.buy_volume,
            "sell_volume": row.sell_volume,
            "buy_turnover": row.buy_turnover,
            "sell_turnover": row.sell_turnover,
        })
        target[minute].merge(synthetic)


def to_month_frame(
    accumulators: dict[int, MinuteAccumulator], start: datetime, end: datetime
) -> pd.DataFrame:
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    index = pd.Index(range(start_ms, end_ms, 60_000), name="start_time_ms", dtype="int64")
    records = []
    for minute in sorted(accumulators):
        row = accumulators[minute]
        records.append({"start_time_ms": minute, **row.__dict__})
    observed = pd.DataFrame.from_records(records).set_index("start_time_ms") if records else pd.DataFrame()
    frame = observed.reindex(index)
    frame.insert(0, "observed", frame["open"].notna() if "open" in frame else False)
    frame["available_at_ms"] = frame.index.to_numpy(dtype="int64") + 60_000
    frame = frame.reset_index()
    if "trade_count" in frame:
        frame["trade_count"] = frame["trade_count"].astype("Float64")
    return frame


def derive_complete_bars(base: pd.DataFrame, rule: str) -> pd.DataFrame:
    temp = base.copy()
    temp.index = pd.to_datetime(temp["start_time_ms"], unit="ms", utc=True)
    grouped = temp.resample(rule, label="left", closed="left", origin="epoch")
    result = pd.DataFrame({
        "start_time_ms": grouped["start_time_ms"].first(),
        "open": grouped["open"].first(),
        "high": grouped["high"].max(),
        "low": grouped["low"].min(),
        "close": grouped["close"].last(),
        **{column: grouped[column].sum(min_count=1) for column in FLOW_COLUMNS},
        "source_rows_observed": grouped["observed"].sum(),
        "source_rows_total": grouped["observed"].size(),
    })
    result["is_complete"] = result["source_rows_observed"] == result["source_rows_total"]
    invalidate = ["open", "high", "low", "close", *FLOW_COLUMNS]
    result.loc[~result["is_complete"], invalidate] = np.nan
    interval_ms = int(pd.Timedelta(rule).total_seconds() * 1000)
    result["available_at_ms"] = result["start_time_ms"].astype("Int64") + interval_ms
    return result.reset_index(drop=True)


def numeric_sanity(frame: pd.DataFrame) -> None:
    observed = frame[frame["observed"]]
    if observed.empty:
        raise ValueError("month has no observed trades")
    if not ((observed["low"] <= observed[["open", "close"]].min(axis=1)).all() and
            (observed["high"] >= observed[["open", "close"]].max(axis=1)).all()):
        raise ValueError("OHLC ordering violation")
    if (observed[list(FLOW_COLUMNS)] < 0).any().any():
        raise ValueError("negative flow aggregate")
    imbalance = (observed["buy_volume"] + observed["sell_volume"] - observed["volume"]).abs()
    tolerance = 1e-9 + observed["volume"].abs() * 1e-10
    if not (imbalance <= tolerance).all():
        raise ValueError("buy/sell volume does not reconcile to total volume")


def build(args: argparse.Namespace) -> Path:
    if args.symbol not in SYMBOLS:
        raise ValueError(f"unsupported symbol {args.symbol}")
    start, end = month_bounds(args.month)
    segment = logical_segment(start)
    output = Path(args.out).resolve() / segment / args.symbol / args.month
    output.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "SMC_ICT_2_LIVE canonical monthly builder/1"})
    month_accumulators: dict[int, MinuteAccumulator] = {}
    sources: list[dict[str, Any]] = []
    missing_days: list[str] = []

    with tempfile.TemporaryDirectory(prefix=f"bybit-{args.symbol}-{args.month}-") as tmp:
        tmpdir = Path(tmp)
        for day in days(start, end):
            iso = day.isoformat()
            url = f"{BASE}/{args.symbol}/{args.symbol}{iso}.csv.gz"
            local = tmpdir / f"{args.symbol}{iso}.csv.gz"
            source = download_file(
                session, url, local, timeout=args.timeout, max_attempts=args.max_attempts
            )
            source["date"] = iso
            if source.get("missing"):
                missing_days.append(iso)
                sources.append(source)
                continue
            daily, rows = aggregate_trade_file(local, chunksize=args.chunksize)
            source["rows"] = rows
            source["observed_minutes"] = len(daily)
            sources.append(source)
            merge_accumulators(month_accumulators, daily)
            local.unlink(missing_ok=True)
            print(json.dumps({"date": iso, "rows": rows, "minutes": len(daily)}), flush=True)

    frame = to_month_frame(month_accumulators, start, end)
    numeric_sanity(frame)
    expected_minutes = len(frame)
    observed_minutes = int(frame["observed"].sum())
    coverage = observed_minutes / expected_minutes
    if coverage < args.min_coverage:
        raise RuntimeError(
            f"observed minute coverage {coverage:.8f} below {args.min_coverage:.8f}; "
            f"missing_days={missing_days}"
        )

    files: list[dict[str, Any]] = []
    bars_dir = output / "trade_bars"
    one_path = bars_dir / "1m.parquet"
    write_parquet(frame, one_path)
    files.append({
        "kind": "trade_bar",
        "name": "1m",
        "path": str(one_path.relative_to(output)),
        "rows": len(frame),
        "bytes": one_path.stat().st_size,
        "sha256": sha256_file(one_path),
    })
    for name, rule in BAR_RULES.items():
        derived = derive_complete_bars(frame, rule)
        path = bars_dir / f"{name}.parquet"
        write_parquet(derived, path)
        files.append({
            "kind": "trade_bar",
            "name": name,
            "path": str(path.relative_to(output)),
            "rows": len(derived),
            "complete_rows": int(derived["is_complete"].sum()),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })

    sources_path = output / "SOURCE_FILES.jsonl"
    sources_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in sources), encoding="utf-8"
    )
    files.append({
        "kind": "source_audit",
        "name": "source_files",
        "path": sources_path.name,
        "rows": len(sources),
        "bytes": sources_path.stat().st_size,
        "sha256": sha256_file(sources_path),
    })

    manifest = {
        "schema_version": 1,
        "dataset_id": f"DS-BYBIT-LINEAR-{args.symbol}-{args.month.replace('-', '')}-TRADEFLOW-V1",
        "dataset_family_id": "DSF-BYBIT-LINEAR-4ASSET-MONTHLY-TRADEFLOW-V1",
        "claim_id": "CLM-20260727-CANONICAL-HALFYEAR-DATA-001",
        "provider": "Bybit official public archive",
        "source_kind": "daily_public_trades",
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
        "causal_availability": (
            "Each 1-minute bar becomes usable only at start_time plus 60 seconds. "
            "Derived bars become usable only at their interval close. Missing source minutes "
            "remain explicit and invalidate the containing derived bar."
        ),
        "coverage": {
            "expected_days": calendar.monthrange(start.year, start.month)[1],
            "source_files_present": len(sources) - len(missing_days),
            "missing_days": missing_days,
            "expected_minutes": expected_minutes,
            "observed_minutes": observed_minutes,
            "missing_minutes": expected_minutes - observed_minutes,
            "minute_coverage": coverage,
        },
        "flow_fields": list(FLOW_COLUMNS),
        "files": files,
        "source_file_count": len(sources),
        "source_raw_bytes": int(sum(int(row.get("bytes", 0)) for row in sources)),
        "source_raw_rows": int(sum(int(row.get("rows", 0)) for row in sources)),
        "source_files_deleted_after_processing": True,
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
    parser.add_argument("--min-coverage", type=float, default=0.999)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = build(args)
    print(json.dumps({"status": "BUILT", "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
