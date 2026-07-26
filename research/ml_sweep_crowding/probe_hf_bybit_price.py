#!/usr/bin/env python3
"""Outcome-sealed coverage/schema probe for immutable Bybit one-minute mirrors."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

DATASET_ID = "rogerdehe/klines-bybit"
FILES = {
    "BTCUSDT": "futures/1m/BTC_USDT_USDT.parquet",
    "ETHUSDT": "futures/1m/ETH_USDT_USDT.parquet",
}
STARTS = {
    "BTCUSDT": pd.Timestamp("2021-01-01T00:00:00Z"),
    "ETHUSDT": pd.Timestamp("2021-03-01T00:00:00Z"),
}
END_EXCLUSIVE = pd.Timestamp("2024-07-01T00:00:00Z")
MINIMUM_COVERAGE = 0.995


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(session: requests.Session, revision: str, repository_path: str, local: Path) -> None:
    encoded = quote(repository_path, safe="/")
    url = f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{revision}/{encoded}?download=true"
    local.parent.mkdir(parents=True, exist_ok=True)
    temp = local.with_suffix(local.suffix + ".part")
    last_error: Exception | None = None
    for _attempt in range(5):
        try:
            with session.get(url, timeout=300, stream=True, allow_redirects=True) as response:
                response.raise_for_status()
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=4 << 20):
                        if chunk:
                            handle.write(chunk)
            if temp.stat().st_size < 1024:
                raise RuntimeError(f"download too small: {url}")
            temp.replace(local)
            return
        except Exception as exc:
            last_error = exc
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"download failed: {repository_path}: {last_error}")


def timestamp_series(frame: pd.DataFrame) -> tuple[pd.DatetimeIndex, str]:
    columns = {str(column).lower(): str(column) for column in frame.columns}
    name = next(
        (
            columns[key]
            for key in ("date", "timestamp", "time", "datetime", "start_time")
            if key in columns
        ),
        None,
    )
    if name is None:
        raise RuntimeError(f"no timestamp column: {list(frame.columns)}")
    raw = frame[name]
    if pd.api.types.is_numeric_dtype(raw):
        numeric = pd.to_numeric(raw, errors="coerce")
        median = float(numeric.dropna().median()) if numeric.notna().any() else math.nan
        if median > 1e15:
            unit = "ns"
        elif median > 1e11:
            unit = "ms"
        else:
            unit = "s"
        parsed = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    else:
        parsed = pd.to_datetime(raw, utc=True, errors="coerce")
    return pd.DatetimeIndex(parsed), name


def inspect(symbol: str, path: Path) -> dict[str, object]:
    frame = pd.read_parquet(path)
    timestamps, time_column = timestamp_series(frame)
    columns = {str(column).lower(): str(column) for column in frame.columns}
    required = ["open", "high", "low", "close", "volume"]
    missing = [name for name in required if name not in columns]
    if missing:
        raise RuntimeError(f"{symbol} missing columns: {missing}")
    normalized = pd.DataFrame({"timestamp": timestamps})
    for name in required:
        normalized[name] = pd.to_numeric(frame[columns[name]], errors="coerce")
    normalized = normalized.dropna(subset=["timestamp", "open", "high", "low", "close"])
    raw_rows = int(len(normalized))
    duplicate_rows = int(normalized.duplicated("timestamp", keep=False).sum())
    normalized = normalized.drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    interval = normalized.loc[
        (normalized.timestamp >= STARTS[symbol]) & (normalized.timestamp < END_EXCLUSIVE)
    ].copy()
    expected = pd.date_range(STARTS[symbol], END_EXCLUSIVE, freq="1min", inclusive="left")
    observed_index = pd.DatetimeIndex(interval.timestamp)
    aligned = bool(((observed_index.asi8 // 60_000_000_000) * 60_000_000_000 == observed_index.asi8).all())
    unique_rows = int(observed_index.nunique())
    coverage = unique_rows / max(len(expected), 1)
    missing_rows = int(len(expected) - unique_rows)
    gaps = observed_index.to_series(index=observed_index).diff().dropna()
    max_gap_minutes = float(gaps.max() / pd.Timedelta(minutes=1)) if len(gaps) else 0.0
    o = interval["open"].to_numpy(dtype=float)
    h = interval["high"].to_numpy(dtype=float)
    l = interval["low"].to_numpy(dtype=float)
    c = interval["close"].to_numpy(dtype=float)
    finite = bool(np.isfinite(np.column_stack([o, h, l, c])).all())
    positive = bool((np.column_stack([o, h, l, c]) > 0).all())
    impossible = int(((h < np.maximum.reduce([o, l, c])) | (l > np.minimum.reduce([o, h, c]))).sum())
    month_counts = (
        interval.assign(month=interval.timestamp.dt.strftime("%Y-%m"))
        .groupby("month", sort=True)
        .size()
        .astype(int)
        .to_dict()
    )
    month_expected = {
        month.strftime("%Y-%m"): int(
            len(
                pd.date_range(
                    max(STARTS[symbol], month),
                    min(END_EXCLUSIVE, month + pd.offsets.MonthBegin(1)),
                    freq="1min",
                    inclusive="left",
                )
            )
        )
        for month in pd.date_range(
            STARTS[symbol].normalize().replace(day=1),
            END_EXCLUSIVE - pd.offsets.MonthBegin(1),
            freq="MS",
        )
    }
    month_coverage = {
        month: month_counts.get(month, 0) / max(expected_rows, 1)
        for month, expected_rows in month_expected.items()
    }
    status = bool(
        coverage >= MINIMUM_COVERAGE
        and aligned
        and finite
        and positive
        and impossible == 0
        and observed_index.min() <= STARTS[symbol] + pd.Timedelta(minutes=2)
        and observed_index.max() >= END_EXCLUSIVE - pd.Timedelta(minutes=2)
    )
    return {
        "symbol": symbol,
        "status": "PASS" if status else "FAIL",
        "repository_path": FILES[symbol],
        "file_bytes": path.stat().st_size,
        "file_sha256": sha256_file(path),
        "columns": [str(column) for column in frame.columns],
        "timestamp_column": time_column,
        "raw_valid_rows": raw_rows,
        "duplicate_rows": duplicate_rows,
        "required_start": STARTS[symbol].isoformat(),
        "required_end_exclusive": END_EXCLUSIVE.isoformat(),
        "expected_minutes": int(len(expected)),
        "observed_unique_minutes": unique_rows,
        "missing_minutes": missing_rows,
        "coverage": float(coverage),
        "minute_aligned": aligned,
        "first_timestamp": observed_index.min().isoformat() if len(observed_index) else None,
        "last_timestamp": observed_index.max().isoformat() if len(observed_index) else None,
        "max_gap_minutes": max_gap_minutes,
        "finite_ohlc": finite,
        "positive_ohlc": positive,
        "impossible_ohlc_rows": impossible,
        "minimum_price": float(np.nanmin(l)) if len(l) else None,
        "maximum_price": float(np.nanmax(h)) if len(h) else None,
        "month_coverage": month_coverage,
    }


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-2-source-probe/1.0"})
    result: dict[str, object] = {
        "schema_version": 1,
        "probe_id": "PROBE-20260727-HF-BYBIT-1M-PINNED-001",
        "claim_id": "CLM-20260727-0245-ML-SWEEP-CROWDING-001",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_id": DATASET_ID,
        "minimum_coverage": MINIMUM_COVERAGE,
        "market_outcome_opened": False,
        "model_opened": False,
        "pnl_opened": False,
        "orders_submitted": False,
        "records": [],
    }
    try:
        response = session.get(f"https://huggingface.co/api/datasets/{DATASET_ID}", timeout=30)
        response.raise_for_status()
        metadata = response.json()
        revision = metadata.get("sha")
        if not isinstance(revision, str) or len(revision) < 20:
            raise RuntimeError("dataset has no immutable revision sha")
        siblings = {
            item.get("rfilename")
            for item in metadata.get("siblings", [])
            if isinstance(item, dict) and isinstance(item.get("rfilename"), str)
        }
        missing = sorted(set(FILES.values()) - siblings)
        if missing:
            raise RuntimeError(f"required one-minute files absent: {missing}")
        result.update(
            {
                "dataset_revision": revision,
                "dataset_last_modified": metadata.get("lastModified"),
                "files": FILES,
            }
        )
        cache = Path(".cache/ml_sweep_crowding/hf_bybit_price") / revision
        records = []
        for symbol, repository_path in FILES.items():
            local = cache / Path(repository_path).name
            download(session, revision, repository_path, local)
            records.append(inspect(symbol, local))
        result["records"] = records
        result["status"] = "PASS" if all(record["status"] == "PASS" for record in records) else "FAIL"
    except Exception as exc:
        result["status"] = "ERROR"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
    output = Path("research/results/ml_sweep_crowding/bybit_price_mirror_probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status"),
        "records": result.get("records"),
        "error": result.get("error"),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
