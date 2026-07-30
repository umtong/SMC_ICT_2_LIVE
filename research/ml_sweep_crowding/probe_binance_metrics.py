#!/usr/bin/env python3
"""Outcome-sealed immutable coverage probe for Binance USD-M metric mirrors."""
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

DATASET_ID = "linxy/USDT-M_Perpetual_Futures"
FILES = {
    "BTCUSDT": "BTCUSDT/BTCUSDT_metrics.parquet",
    "ETHUSDT": "ETHUSDT/ETHUSDT_metrics.parquet",
}
WINDOW_START = pd.Timestamp("2021-01-01T00:00:00Z")
WINDOW_END_EXCLUSIVE = pd.Timestamp("2024-07-01T00:00:00Z")
REQUIRED = [
    "create_time",
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_timestamp(series: pd.Series) -> pd.DatetimeIndex:
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.DatetimeIndex(pd.to_datetime(series, utc=True, errors="coerce"))
    numeric = pd.to_numeric(series, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    if len(finite) and float(finite.median()) > 1e15:
        unit = "ns"
    elif len(finite) and float(finite.median()) > 1e12:
        unit = "ms"
    elif len(finite) and float(finite.median()) > 1e9:
        unit = "s"
    else:
        return pd.DatetimeIndex(pd.to_datetime(series, utc=True, errors="coerce"))
    return pd.DatetimeIndex(pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce"))


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
                raise RuntimeError(f"download too small: {repository_path}")
            temp.replace(local)
            return
        except Exception as exc:
            last_error = exc
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"download failed: {repository_path}: {last_error}")


def month_windows() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    starts = pd.date_range(WINDOW_START, WINDOW_END_EXCLUSIVE, freq="MS", inclusive="left")
    return [(start, min(start + pd.offsets.MonthBegin(1), WINDOW_END_EXCLUSIVE)) for start in starts]


def inspect(symbol: str, path: Path) -> dict[str, object]:
    frame = pd.read_parquet(path, columns=REQUIRED)
    timestamps = parse_timestamp(frame.pop("create_time"))
    frame.index = timestamps
    invalid_timestamp_rows = int(frame.index.isna().sum())
    frame = frame[~frame.index.isna()].sort_index()
    duplicate_rows = int(frame.index.duplicated(keep=False).sum())
    frame = frame[~frame.index.duplicated(keep="last")]
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    interval = frame.loc[(frame.index >= WINDOW_START) & (frame.index < WINDOW_END_EXCLUSIVE)]
    expected_total = len(pd.date_range(WINDOW_START, WINDOW_END_EXCLUSIVE, freq="5min", inclusive="left"))
    observed_slots = int(interval.index.floor("5min").nunique())
    month_coverage: dict[str, float] = {}
    month_observed: dict[str, int] = {}
    for start, end in month_windows():
        expected = len(pd.date_range(start, end, freq="5min", inclusive="left"))
        observed = int(interval.loc[(interval.index >= start) & (interval.index < end)].index.floor("5min").nunique())
        key = start.strftime("%Y-%m")
        month_observed[key] = observed
        month_coverage[key] = observed / max(expected, 1)
    gaps = interval.index.to_series(index=interval.index).diff().dropna()
    value_quality = {}
    for column in frame.columns:
        series = interval[column]
        finite = pd.to_numeric(series, errors="coerce")
        value_quality[column] = {
            "non_null_share": float(finite.notna().mean()) if len(finite) else 0.0,
            "positive_share": float((finite > 0).mean()) if len(finite) else 0.0,
            "unique_values": int(finite.nunique(dropna=True)),
            "minimum": float(finite.min()) if finite.notna().any() else None,
            "maximum": float(finite.max()) if finite.notna().any() else None,
        }
    return {
        "symbol": symbol,
        "repository_path": FILES[symbol],
        "file_bytes": path.stat().st_size,
        "file_sha256": sha256_file(path),
        "columns": REQUIRED,
        "raw_rows": int(len(frame) + invalid_timestamp_rows),
        "invalid_timestamp_rows": invalid_timestamp_rows,
        "duplicate_rows": duplicate_rows,
        "first_timestamp_all": frame.index.min().isoformat() if len(frame) else None,
        "last_timestamp_all": frame.index.max().isoformat() if len(frame) else None,
        "first_timestamp_window": interval.index.min().isoformat() if len(interval) else None,
        "last_timestamp_window": interval.index.max().isoformat() if len(interval) else None,
        "expected_5m_slots": int(expected_total),
        "observed_5m_slots": observed_slots,
        "coverage_5m": observed_slots / max(expected_total, 1),
        "max_gap_minutes": float(gaps.max() / pd.Timedelta(minutes=1)) if len(gaps) else None,
        "median_gap_minutes": float(gaps.median() / pd.Timedelta(minutes=1)) if len(gaps) else None,
        "month_observed": month_observed,
        "month_coverage": month_coverage,
        "value_quality": value_quality,
    }


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-2-source-probe/1.0"})
    result: dict[str, object] = {
        "schema_version": 1,
        "probe_id": "PROBE-20260727-BINANCE-METRICS-PINNED-001",
        "claim_id": "CLM-20260727-0245-ML-SWEEP-CROWDING-001",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_id": DATASET_ID,
        "window_start": WINDOW_START.isoformat(),
        "window_end_exclusive": WINDOW_END_EXCLUSIVE.isoformat(),
        "market_price_opened": False,
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
            raise RuntimeError(f"required metric files absent: {missing}")
        result.update({
            "dataset_revision": revision,
            "dataset_last_modified": metadata.get("lastModified"),
            "files": FILES,
        })
        cache = Path(".cache/ml_sweep_crowding/binance_metrics_probe") / revision
        records = []
        for symbol, repository_path in FILES.items():
            local = cache / Path(repository_path).name
            download(session, revision, repository_path, local)
            records.append(inspect(symbol, local))
        result["records"] = records
        result["status"] = "COMPLETE"
    except Exception as exc:
        result["status"] = "ERROR"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
    output = Path("research/results/ml_sweep_crowding/binance_metrics_probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
