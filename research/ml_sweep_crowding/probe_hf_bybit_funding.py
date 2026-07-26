#!/usr/bin/env python3
"""Outcome-sealed probe of a public Bybit funding-rate mirror.

The probe pins the Hugging Face dataset revision before downloading files.  It
opens no strategy price path, model, trade, PnL or official evaluation period.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests

DATASET_ID = "rogerdehe/klines-bybit"
API_URL = f"https://huggingface.co/api/datasets/{DATASET_ID}"
EXPECTED = {
    "BTCUSDT": "futures/1h/BTC_USDT_USDT-funding_rate.parquet",
    "ETHUSDT": "futures/1h/ETH_USDT_USDT-funding_rate.parquet",
}
MIN_START = {
    "BTCUSDT": pd.Timestamp("2021-01-01T00:00:00Z"),
    "ETHUSDT": pd.Timestamp("2021-03-01T00:00:00Z"),
}
REQUIRED_END = pd.Timestamp("2024-07-01T00:00:00Z")
MAX_ABS_RATE = 0.10


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_json(session: requests.Session, url: str) -> dict[str, Any]:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected JSON payload from {url}")
    return payload


def download(session: requests.Session, revision: str, filename: str, out: Path) -> None:
    encoded = quote(filename, safe="/")
    url = f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{revision}/{encoded}?download=true"
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(out.suffix + ".part")
    last_error: Exception | None = None
    for _attempt in range(5):
        try:
            with session.get(url, timeout=120, stream=True, allow_redirects=True) as response:
                response.raise_for_status()
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        if chunk:
                            handle.write(chunk)
            if temp.stat().st_size < 64:
                raise RuntimeError(f"download too small: {url}")
            temp.replace(out)
            return
        except Exception as exc:
            last_error = exc
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"download failed: {url}: {last_error}")


def normalize(frame: pd.DataFrame) -> tuple[pd.DataFrame, str, str]:
    columns = {str(column).lower(): str(column) for column in frame.columns}
    time_name = next(
        (
            columns[name]
            for name in ("date", "timestamp", "time", "datetime", "funding_time")
            if name in columns
        ),
        None,
    )
    if time_name is None:
        raise RuntimeError(f"no timestamp column in {list(frame.columns)}")
    rate_name = next(
        (
            columns[name]
            for name in ("funding_rate", "fundingrate", "rate", "close")
            if name in columns
        ),
        None,
    )
    if rate_name is None:
        raise RuntimeError(f"no funding-rate column in {list(frame.columns)}")
    time_raw = frame[time_name]
    if pd.api.types.is_numeric_dtype(time_raw):
        numeric = pd.to_numeric(time_raw, errors="coerce")
        median = float(numeric.dropna().median()) if numeric.notna().any() else math.nan
        unit = "ms" if median > 1e11 else "s"
        timestamp = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    else:
        timestamp = pd.to_datetime(time_raw, utc=True, errors="coerce")
    rate = pd.to_numeric(frame[rate_name], errors="coerce")
    normalized = pd.DataFrame({"timestamp": timestamp, "funding_rate": rate})
    normalized = (
        normalized.dropna()
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    return normalized, time_name, rate_name


def inspect(symbol: str, path: Path) -> dict[str, Any]:
    frame = pd.read_parquet(path)
    normalized, time_column, rate_column = normalize(frame)
    if normalized.empty:
        raise RuntimeError(f"{symbol} normalized funding frame empty")
    timestamps = pd.DatetimeIndex(normalized["timestamp"])
    rates = normalized["funding_rate"].astype(float)
    gaps = timestamps.to_series(index=timestamps).diff().dropna()
    before_end = normalized[normalized["timestamp"] < REQUIRED_END]
    after_start = before_end[before_end["timestamp"] >= MIN_START[symbol]]
    expected = pd.date_range(MIN_START[symbol], REQUIRED_END, freq="8h", inclusive="left")
    aligned = pd.DatetimeIndex(after_start["timestamp"]).floor("8h").nunique()
    coverage = aligned / max(len(expected), 1)
    max_gap_hours = float(gaps.max() / pd.Timedelta(hours=1)) if len(gaps) else 0.0
    median_gap_hours = float(gaps.median() / pd.Timedelta(hours=1)) if len(gaps) else 0.0
    max_abs = float(rates.abs().max())
    finite = bool(pd.Series(rates).map(math.isfinite).all())
    status = bool(
        timestamps.min() <= MIN_START[symbol] + pd.Timedelta(hours=16)
        and timestamps.max() >= REQUIRED_END - pd.Timedelta(hours=16)
        and coverage >= 0.98
        and 4.0 <= median_gap_hours <= 12.01
        and max_gap_hours <= 24.01
        and finite
        and max_abs <= MAX_ABS_RATE
    )
    return {
        "symbol": symbol,
        "status": "PASS" if status else "FAIL",
        "file": path.name,
        "file_bytes": path.stat().st_size,
        "file_sha256": sha256_file(path),
        "columns": [str(column) for column in frame.columns],
        "timestamp_column": time_column,
        "rate_column": rate_column,
        "rows_raw": int(len(frame)),
        "rows_normalized": int(len(normalized)),
        "first_timestamp": timestamps.min().isoformat(),
        "last_timestamp": timestamps.max().isoformat(),
        "required_start": MIN_START[symbol].isoformat(),
        "required_end_exclusive": REQUIRED_END.isoformat(),
        "expected_8h_rows": int(len(expected)),
        "observed_8h_slots": int(aligned),
        "coverage_8h": float(coverage),
        "median_gap_hours": median_gap_hours,
        "max_gap_hours": max_gap_hours,
        "duplicate_timestamps_removed": int(len(frame) - len(normalized)),
        "min_rate": float(rates.min()),
        "max_rate": float(rates.max()),
        "max_abs_rate": max_abs,
        "finite_rates": finite,
        "zero_rate_share": float((rates == 0).mean()),
        "unique_rate_count": int(rates.nunique()),
    }


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-2-source-probe/1.0"})
    result: dict[str, Any] = {
        "schema_version": 1,
        "probe_id": "PROBE-20260727-HF-BYBIT-FUNDING-PINNED-002",
        "claim_id": "CLM-20260727-0245-ML-SWEEP-CROWDING-001",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_id": DATASET_ID,
        "market_price_opened": False,
        "model_opened": False,
        "pnl_opened": False,
        "official_period_opened": False,
        "credentials_used": False,
        "orders_submitted": False,
        "records": [],
    }
    try:
        metadata = get_json(session, API_URL)
        revision = metadata.get("sha")
        if not isinstance(revision, str) or len(revision) < 20:
            raise RuntimeError("Hugging Face metadata has no immutable dataset sha")
        siblings = {
            item.get("rfilename")
            for item in metadata.get("siblings", [])
            if isinstance(item, dict) and isinstance(item.get("rfilename"), str)
        }
        missing = sorted(set(EXPECTED.values()) - siblings)
        if missing:
            raise RuntimeError(f"expected funding files missing at revision {revision}: {missing}")
        result.update(
            {
                "dataset_revision": revision,
                "dataset_last_modified": metadata.get("lastModified"),
                "dataset_sibling_count": len(siblings),
                "expected_files": EXPECTED,
            }
        )
        cache = Path(".cache/ml_sweep_crowding/hf_bybit_funding") / revision
        for symbol, filename in EXPECTED.items():
            local = cache / Path(filename).name
            download(session, revision, filename, local)
            record = inspect(symbol, local)
            record["repository_path"] = filename
            result["records"].append(record)
        result["status"] = (
            "PASS"
            if result["records"] and all(row["status"] == "PASS" for row in result["records"])
            else "FAIL"
        )
    except Exception as exc:
        result["status"] = "ERROR"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
    output = Path("research/results/ml_sweep_crowding/bybit_funding_mirror_probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
