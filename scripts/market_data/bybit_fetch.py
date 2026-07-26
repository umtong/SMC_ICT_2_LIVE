"""Deterministic pagination and normalization for official Bybit V5 market streams."""
from __future__ import annotations

from typing import Any

import pandas as pd

try:
    from .bybit_client import BybitPublicClient, PageAudit, SourceError, page_audit
except ImportError:  # direct script execution
    from bybit_client import BybitPublicClient, PageAudit, SourceError, page_audit


def fetch_kline_stream(
    client: BybitPublicClient,
    *,
    symbol: str,
    stream: str,
    path: str,
    start_ms: int,
    end_exclusive_ms: int,
) -> tuple[pd.DataFrame, list[PageAudit]]:
    cursor_end = end_exclusive_ms - 1
    rows: list[list[str]] = []
    audits: list[PageAudit] = []
    while cursor_end >= start_ms:
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": "1",
            "start": start_ms,
            "end": cursor_end,
            "limit": 1000,
        }
        payload, raw = client.get(path, params)
        page = payload.get("result", {}).get("list", []) or []
        timestamps = [int(row[0]) for row in page]
        audits.append(page_audit(stream=stream, path=path, params=params, raw=raw, timestamps=timestamps))
        if not page:
            break
        rows.extend(page)
        oldest = min(timestamps)
        if oldest <= start_ms:
            break
        if oldest > cursor_end:
            raise SourceError(f"{stream}: non-progressing pagination at {oldest}")
        cursor_end = oldest - 1

    columns = ["start_time_ms", "open", "high", "low", "close"]
    width = 5
    if stream == "trade_price_1m":
        columns += ["volume", "turnover"]
        width = 7
    if not rows:
        return pd.DataFrame(columns=columns), audits
    frame = pd.DataFrame([row[:width] for row in rows if len(row) >= width], columns=columns)
    frame["start_time_ms"] = pd.to_numeric(frame["start_time_ms"], errors="raise").astype("int64")
    for column in columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.drop_duplicates("start_time_ms", keep="last").sort_values("start_time_ms")
    frame = frame[(frame.start_time_ms >= start_ms) & (frame.start_time_ms < end_exclusive_ms)]
    return frame.reset_index(drop=True), audits


def fetch_funding(
    client: BybitPublicClient,
    *,
    symbol: str,
    start_ms: int,
    end_exclusive_ms: int,
) -> tuple[pd.DataFrame, list[PageAudit]]:
    path = "/v5/market/funding/history"
    cursor_end = end_exclusive_ms - 1
    records: list[dict[str, Any]] = []
    audits: list[PageAudit] = []
    while cursor_end >= start_ms:
        params = {
            "category": "linear",
            "symbol": symbol,
            "startTime": start_ms,
            "endTime": cursor_end,
            "limit": 200,
        }
        payload, raw = client.get(path, params)
        page = payload.get("result", {}).get("list", []) or []
        timestamps = [int(row["fundingRateTimestamp"]) for row in page]
        audits.append(page_audit(
            stream="funding_events", path=path, params=params, raw=raw, timestamps=timestamps
        ))
        if not page:
            break
        records.extend(page)
        oldest = min(timestamps)
        if oldest <= start_ms:
            break
        if oldest > cursor_end:
            raise SourceError(f"funding_events: non-progressing pagination at {oldest}")
        cursor_end = oldest - 1
    frame = pd.DataFrame({
        "timestamp_ms": [int(row["fundingRateTimestamp"]) for row in records],
        "funding_rate": [float(row["fundingRate"]) for row in records],
    }) if records else pd.DataFrame(columns=["timestamp_ms", "funding_rate"])
    if not frame.empty:
        frame = frame.drop_duplicates("timestamp_ms", keep="last").sort_values("timestamp_ms")
        frame = frame[(frame.timestamp_ms >= start_ms) & (frame.timestamp_ms < end_exclusive_ms)]
    return frame.reset_index(drop=True), audits


def fetch_cursor_series(
    client: BybitPublicClient,
    *,
    symbol: str,
    stream: str,
    path: str,
    interval_param: tuple[str, str],
    start_ms: int,
    end_exclusive_ms: int,
) -> tuple[pd.DataFrame, list[PageAudit]]:
    records: list[dict[str, Any]] = []
    audits: list[PageAudit] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    limit = 200 if stream == "open_interest_5m" else 500
    while True:
        params: dict[str, Any] = {
            "category": "linear",
            "symbol": symbol,
            interval_param[0]: interval_param[1],
            "startTime": start_ms,
            "endTime": end_exclusive_ms - 1,
            "limit": limit,
        }
        if cursor:
            params["cursor"] = cursor
        payload, raw = client.get(path, params)
        result = payload.get("result", {})
        page = result.get("list", []) or []
        timestamps = [int(row["timestamp"]) for row in page]
        audits.append(page_audit(stream=stream, path=path, params=params, raw=raw, timestamps=timestamps))
        records.extend(page)
        next_cursor = result.get("nextPageCursor") or ""
        if not page or not next_cursor:
            break
        if next_cursor in seen_cursors:
            raise SourceError(f"{stream}: repeated cursor {next_cursor}")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    if stream == "open_interest_5m":
        frame = pd.DataFrame({
            "timestamp_ms": [int(row["timestamp"]) for row in records],
            "open_interest": [float(row["openInterest"]) for row in records],
        }) if records else pd.DataFrame(columns=["timestamp_ms", "open_interest"])
    else:
        frame = pd.DataFrame({
            "timestamp_ms": [int(row["timestamp"]) for row in records],
            "buy_ratio": [float(row["buyRatio"]) for row in records],
            "sell_ratio": [float(row["sellRatio"]) for row in records],
        }) if records else pd.DataFrame(columns=["timestamp_ms", "buy_ratio", "sell_ratio"])
    if not frame.empty:
        frame = frame.drop_duplicates("timestamp_ms", keep="last").sort_values("timestamp_ms")
        frame = frame[(frame.timestamp_ms >= start_ms) & (frame.timestamp_ms < end_exclusive_ms)]
    return frame.reset_index(drop=True), audits
