#!/usr/bin/env python3
"""Probe historical Bybit V5 coverage before opening the canonical full build."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

try:
    from .bybit_client import BybitPublicClient, PageAudit
    from .bybit_fetch import fetch_cursor_series, fetch_funding, fetch_kline_stream
    from .canonical_spec import MS_MINUTE, SYMBOLS, utc_ms
except ImportError:  # direct script execution
    from bybit_client import BybitPublicClient, PageAudit
    from bybit_fetch import fetch_cursor_series, fetch_funding, fetch_kline_stream
    from canonical_spec import MS_MINUTE, SYMBOLS, utc_ms

DAY_MS = 24 * 60 * MS_MINUTE
PROBE_WINDOWS = {
    "PRE_2024_2023": "2023-06-15T00:00:00Z",
    "2024_H1": "2024-03-15T00:00:00Z",
    "2024_H2": "2024-09-15T00:00:00Z",
    "2025_H1": "2025-03-15T00:00:00Z",
    "2025_H2": "2025-09-15T00:00:00Z",
    "2026_H1": "2026-03-15T00:00:00Z",
}
KLINE_STREAMS = (
    ("trade_price_1m", "/v5/market/kline"),
    ("mark_price_1m", "/v5/market/mark-price-kline"),
    ("index_price_1m", "/v5/market/index-price-kline"),
    ("premium_index_1m", "/v5/market/premium-index-price-kline"),
)


def _audit_dicts(audits: list[PageAudit]) -> list[dict[str, Any]]:
    return [asdict(audit) for audit in audits]


def _summary(
    *,
    symbol: str,
    segment: str,
    stream: str,
    frame: pd.DataFrame,
    timestamp_col: str,
    expected_rows: int | None,
    minimum_coverage: float | None,
    minimum_rows: int,
    audits: list[PageAudit],
    start_ms: int,
    end_exclusive_ms: int,
) -> dict[str, Any]:
    timestamps = (
        pd.to_numeric(frame[timestamp_col], errors="coerce").dropna().astype("int64")
        if timestamp_col in frame.columns
        else pd.Series(dtype="int64")
    )
    rows = int(len(timestamps))
    coverage = None if expected_rows is None else rows / expected_rows
    inside_window = bool(
        timestamps.empty
        or (int(timestamps.min()) >= start_ms and int(timestamps.max()) < end_exclusive_ms)
    )
    passed = rows >= minimum_rows and inside_window
    if minimum_coverage is not None:
        passed = passed and coverage is not None and coverage >= minimum_coverage
    return {
        "symbol": symbol,
        "physical_segment": segment,
        "stream": stream,
        "status": "PASS" if passed else "FAIL",
        "start_ms": start_ms,
        "end_exclusive_ms": end_exclusive_ms,
        "rows": rows,
        "expected_rows": expected_rows,
        "coverage": coverage,
        "minimum_coverage": minimum_coverage,
        "minimum_rows": minimum_rows,
        "first_timestamp_ms": None if timestamps.empty else int(timestamps.min()),
        "last_timestamp_ms": None if timestamps.empty else int(timestamps.max()),
        "inside_requested_window": inside_window,
        "source_page_count": len(audits),
        "source_pages": _audit_dicts(audits),
    }


def _capture(
    records: list[dict[str, Any]],
    *,
    symbol: str,
    segment: str,
    stream: str,
    operation: Callable[[], tuple[pd.DataFrame, list[PageAudit]]],
    timestamp_col: str,
    expected_rows: int | None,
    minimum_coverage: float | None,
    minimum_rows: int,
    start_ms: int,
    end_exclusive_ms: int,
) -> None:
    try:
        frame, audits = operation()
        records.append(_summary(
            symbol=symbol,
            segment=segment,
            stream=stream,
            frame=frame,
            timestamp_col=timestamp_col,
            expected_rows=expected_rows,
            minimum_coverage=minimum_coverage,
            minimum_rows=minimum_rows,
            audits=audits,
            start_ms=start_ms,
            end_exclusive_ms=end_exclusive_ms,
        ))
    except Exception as exc:  # preserve all endpoint failures in one immutable probe
        records.append({
            "symbol": symbol,
            "physical_segment": segment,
            "stream": stream,
            "status": "ERROR",
            "start_ms": start_ms,
            "end_exclusive_ms": end_exclusive_ms,
            "error_type": type(exc).__name__,
            "error": str(exc),
        })


def probe(args: argparse.Namespace) -> dict[str, Any]:
    client = BybitPublicClient(
        base_url=args.base_url,
        timeout_s=args.timeout,
        min_request_interval_s=args.min_request_interval,
        max_attempts=args.max_attempts,
    )
    records: list[dict[str, Any]] = []
    for segment, start_iso in PROBE_WINDOWS.items():
        start_ms = utc_ms(start_iso)
        end_exclusive_ms = start_ms + DAY_MS
        for symbol in SYMBOLS:
            for stream, path in KLINE_STREAMS:
                _capture(
                    records,
                    symbol=symbol,
                    segment=segment,
                    stream=stream,
                    operation=lambda symbol=symbol, stream=stream, path=path, start_ms=start_ms, end_exclusive_ms=end_exclusive_ms: fetch_kline_stream(
                        client,
                        symbol=symbol,
                        stream=stream,
                        path=path,
                        start_ms=start_ms,
                        end_exclusive_ms=end_exclusive_ms,
                    ),
                    timestamp_col="start_time_ms",
                    expected_rows=1440,
                    minimum_coverage=args.minimum_kline_coverage,
                    minimum_rows=1,
                    start_ms=start_ms,
                    end_exclusive_ms=end_exclusive_ms,
                )
            _capture(
                records,
                symbol=symbol,
                segment=segment,
                stream="open_interest_5m",
                operation=lambda symbol=symbol, start_ms=start_ms, end_exclusive_ms=end_exclusive_ms: fetch_cursor_series(
                    client,
                    symbol=symbol,
                    stream="open_interest_5m",
                    path="/v5/market/open-interest",
                    interval_param=("intervalTime", "5min"),
                    start_ms=start_ms,
                    end_exclusive_ms=end_exclusive_ms,
                ),
                timestamp_col="timestamp_ms",
                expected_rows=288,
                minimum_coverage=args.minimum_aux_coverage,
                minimum_rows=1,
                start_ms=start_ms,
                end_exclusive_ms=end_exclusive_ms,
            )
            _capture(
                records,
                symbol=symbol,
                segment=segment,
                stream="account_ratio_5m",
                operation=lambda symbol=symbol, start_ms=start_ms, end_exclusive_ms=end_exclusive_ms: fetch_cursor_series(
                    client,
                    symbol=symbol,
                    stream="account_ratio_5m",
                    path="/v5/market/account-ratio",
                    interval_param=("period", "5min"),
                    start_ms=start_ms,
                    end_exclusive_ms=end_exclusive_ms,
                ),
                timestamp_col="timestamp_ms",
                expected_rows=288,
                minimum_coverage=args.minimum_aux_coverage,
                minimum_rows=1,
                start_ms=start_ms,
                end_exclusive_ms=end_exclusive_ms,
            )
            _capture(
                records,
                symbol=symbol,
                segment=segment,
                stream="funding_events",
                operation=lambda symbol=symbol, start_ms=start_ms, end_exclusive_ms=end_exclusive_ms: fetch_funding(
                    client,
                    symbol=symbol,
                    start_ms=start_ms,
                    end_exclusive_ms=end_exclusive_ms,
                ),
                timestamp_col="timestamp_ms",
                expected_rows=None,
                minimum_coverage=None,
                minimum_rows=1,
                start_ms=start_ms,
                end_exclusive_ms=end_exclusive_ms,
            )
    failures = [record for record in records if record["status"] != "PASS"]
    return {
        "schema_version": 1,
        "probe_id": "PROBE-BYBIT-LINEAR-4ASSET-HISTORY-V1",
        "claim_id": "CLM-20260727-CANONICAL-HALFYEAR-DATA-001",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "base_url": args.base_url,
        "symbols": list(SYMBOLS),
        "windows": PROBE_WINDOWS,
        "record_count": len(records),
        "pass_count": len(records) - len(failures),
        "failure_count": len(failures),
        "status": "PASS" if not failures else "FAIL",
        "records": records,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-url", default="https://api.bybit.com")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--min-request-interval", type=float, default=0.10)
    parser.add_argument("--minimum-kline-coverage", type=float, default=0.995)
    parser.add_argument("--minimum-aux-coverage", type=float, default=0.95)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    result = probe(args)
    path = args.out / "PROBE_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "records": result["record_count"],
        "passed": result["pass_count"],
        "failed": result["failure_count"],
        "output": str(path),
    }, indent=2, sort_keys=True))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
