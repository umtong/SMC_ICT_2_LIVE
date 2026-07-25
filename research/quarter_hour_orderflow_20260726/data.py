from __future__ import annotations

import csv
import hashlib
import json
import math
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests

import source_probe

DAY_MS = 24 * 60 * 60 * 1_000
MINUTE_MS = 60_000
QUARTER_MS = 15 * MINUTE_MS
WINDOW_MS = 10_000
CONTROL_OFFSET_MS = 7 * MINUTE_MS


@dataclass(frozen=True, slots=True)
class SourceRecord:
    symbol: str
    data_type: str
    partition: str
    url: str
    checksum_url: str
    bytes: int
    sha256: str
    expected_sha256: str
    cache_hit: bool


@dataclass(slots=True)
class DayData:
    symbol: str
    date: str
    windows: pd.DataFrame
    contract: pd.DataFrame
    mark: pd.DataFrame
    funding: pd.DataFrame
    source_records: list[SourceRecord]


def utc_day_start_ms(date: str) -> int:
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1_000)


def _boolean(raw: str) -> bool:
    return raw.strip().lower() in {"true", "1", "t", "yes"}


def _csv_rows(path: Path) -> Iterable[list[str]]:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        if len(members) != 1:
            raise ValueError(f"expected one CSV member in {path}, got {members}")
        with archive.open(members[0], "r") as raw:
            text = (line.decode("utf-8-sig", errors="strict") for line in raw)
            reader = csv.reader(text)
            first = next(reader, None)
            if first is None:
                raise ValueError(f"empty CSV in {path}")
            if source_probe._is_header(first):
                yield [item.strip() for item in first]
                yield from reader
            else:
                yield [f"c{index}" for index in range(len(first))]
                yield first
                yield from reader


def ensure_verified_archive(
    session: requests.Session,
    cache: Path,
    symbol: str,
    data_type: str,
    date: str,
) -> tuple[Path, SourceRecord]:
    url, checksum_url, partition = source_probe.archive_urls(symbol, data_type, date)
    target = cache / data_type / symbol / Path(url).name
    checksum_target = cache / data_type / symbol / Path(checksum_url).name
    archive_cache_hit = target.exists() and target.stat().st_size > 0
    status, payload, error = source_probe._download(session, url, target)
    checksum_status, checksum_payload, checksum_error = source_probe._download(
        session, checksum_url, checksum_target
    )
    if status != 200 or checksum_status != 200:
        raise RuntimeError(
            f"source unavailable {url}: archive={status} {error}; checksum={checksum_status} {checksum_error}"
        )
    digest = hashlib.sha256(payload).hexdigest()
    expected = source_probe.parse_expected_checksum(checksum_payload)
    if expected is None or digest != expected:
        raise ValueError(f"checksum mismatch for {url}: observed={digest} expected={expected}")
    return target, SourceRecord(
        symbol=symbol,
        data_type=data_type,
        partition=partition,
        url=url,
        checksum_url=checksum_url,
        bytes=len(payload),
        sha256=digest,
        expected_sha256=expected,
        cache_hit=archive_cache_hit,
    )


def load_agg_windows(path: Path, date: str) -> pd.DataFrame:
    start = utc_day_start_ms(date)
    end = start + DAY_MS
    accumulators: dict[tuple[str, int], dict[str, float | int | None]] = {}
    rows = iter(_csv_rows(path))
    header = next(rows)
    if len(header) < 7:
        raise ValueError(f"aggTrades width below seven: {header}")
    for row in rows:
        if len(row) < 7:
            raise ValueError(f"short aggTrades row in {path}: {row}")
        timestamp = source_probe.normalize_timestamp_ms(row[5])
        if timestamp < start or timestamp >= end:
            continue
        quarter_start = timestamp // QUARTER_MS * QUARTER_MS
        delta = timestamp - quarter_start
        phase: str | None = None
        event_start: int | None = None
        if 0 <= delta < WINDOW_MS:
            phase, event_start = "quarter", quarter_start
        elif CONTROL_OFFSET_MS <= delta < CONTROL_OFFSET_MS + WINDOW_MS:
            phase, event_start = "control", quarter_start + CONTROL_OFFSET_MS
        if phase is None or event_start is None:
            continue
        price = float(row[1])
        quantity = float(row[2])
        if not (math.isfinite(price) and math.isfinite(quantity) and price > 0 and quantity > 0):
            continue
        notional = price * quantity
        signed = -notional if _boolean(row[6]) else notional
        key = (phase, event_start)
        item = accumulators.get(key)
        if item is None:
            accumulators[key] = {
                "first_price": price,
                "last_price": price,
                "total_notional": notional,
                "signed_notional": signed,
                "trade_count": 1,
                "first_trade_ms": timestamp,
                "last_trade_ms": timestamp,
            }
        else:
            item["last_price"] = price
            item["total_notional"] = float(item["total_notional"]) + notional
            item["signed_notional"] = float(item["signed_notional"]) + signed
            item["trade_count"] = int(item["trade_count"]) + 1
            item["last_trade_ms"] = timestamp

    output: list[dict] = []
    for quarter_start in range(start, end, QUARTER_MS):
        for phase, event_start in (
            ("quarter", quarter_start),
            ("control", quarter_start + CONTROL_OFFSET_MS),
        ):
            item = accumulators.get((phase, event_start))
            if item is None:
                output.append({
                    "phase": phase,
                    "event_start_ms": event_start,
                    "decision_ms": event_start + WINDOW_MS,
                    "first_price": np.nan,
                    "last_price": np.nan,
                    "opening_return": np.nan,
                    "total_notional": 0.0,
                    "signed_notional": 0.0,
                    "imbalance": np.nan,
                    "trade_count": 0,
                    "first_trade_ms": np.nan,
                    "last_trade_ms": np.nan,
                    "valid": False,
                })
                continue
            total = float(item["total_notional"])
            first_price = float(item["first_price"])
            last_price = float(item["last_price"])
            output.append({
                "phase": phase,
                "event_start_ms": event_start,
                "decision_ms": event_start + WINDOW_MS,
                "first_price": first_price,
                "last_price": last_price,
                "opening_return": math.log(last_price / first_price),
                "total_notional": total,
                "signed_notional": float(item["signed_notional"]),
                "imbalance": float(item["signed_notional"]) / total,
                "trade_count": int(item["trade_count"]),
                "first_trade_ms": int(item["first_trade_ms"]),
                "last_trade_ms": int(item["last_trade_ms"]),
                "valid": True,
            })
    frame = pd.DataFrame(output).sort_values(["event_start_ms", "phase"]).reset_index(drop=True)
    if len(frame) != 192:
        raise AssertionError(f"expected 192 phase windows, got {len(frame)}")
    return frame


def _load_kline(path: Path, date: str, *, contract: bool) -> pd.DataFrame:
    start = utc_day_start_ms(date)
    expected = np.arange(start, start + DAY_MS, MINUTE_MS, dtype=np.int64)
    rows = iter(_csv_rows(path))
    header = next(rows)
    records: list[dict] = []
    for row in rows:
        if len(row) < 5:
            raise ValueError(f"short kline row in {path}: {row}")
        open_time = source_probe.normalize_timestamp_ms(row[0])
        if open_time < start or open_time >= start + DAY_MS:
            continue
        values = [float(row[index]) for index in (1, 2, 3, 4)]
        if not all(math.isfinite(value) and value > 0 for value in values):
            continue
        record = {
            "open_ms": open_time,
            "open": values[0],
            "high": values[1],
            "low": values[2],
            "close": values[3],
        }
        if contract:
            if len(row) < 11:
                raise ValueError(f"contract kline lacks quote-volume fields: {row}")
            quote_volume = float(row[7])
            record["quote_volume"] = quote_volume if math.isfinite(quote_volume) and quote_volume >= 0 else np.nan
        records.append(record)
    frame = pd.DataFrame(records)
    if frame.empty:
        frame = pd.DataFrame(index=expected)
    else:
        if frame.open_ms.duplicated().any():
            raise ValueError(f"duplicate kline open times in {path}")
        frame = frame.set_index("open_ms").sort_index().reindex(expected)
    required = ["open", "high", "low", "close"] + (["quote_volume"] if contract else [])
    for column in required:
        if column not in frame:
            frame[column] = np.nan
    frame["valid"] = np.isfinite(frame[required].to_numpy(float)).all(axis=1)
    frame.index.name = "open_ms"
    return frame


def load_contract_klines(path: Path, date: str) -> pd.DataFrame:
    return _load_kline(path, date, contract=True)


def load_mark_klines(path: Path, date: str) -> pd.DataFrame:
    return _load_kline(path, date, contract=False)


def _normalized_header(header: list[str]) -> dict[str, int]:
    return {
        item.strip().lower().replace(" ", "_").replace("-", "_"): index
        for index, item in enumerate(header)
    }


def load_funding(path: Path) -> pd.DataFrame:
    rows = iter(_csv_rows(path))
    header = next(rows)
    mapping = _normalized_header(header)
    time_candidates = ("calc_time", "funding_time", "fundingtime", "time", "timestamp")
    rate_candidates = ("last_funding_rate", "funding_rate", "fundingrate", "rate")
    time_index = next((mapping[name] for name in time_candidates if name in mapping), 0)
    rate_index = next((mapping[name] for name in rate_candidates if name in mapping), len(header) - 1)
    records: list[tuple[int, float]] = []
    previous: int | None = None
    for row in rows:
        if max(time_index, rate_index) >= len(row):
            raise ValueError(f"short funding row in {path}: {row}")
        timestamp = source_probe.normalize_timestamp_ms(row[time_index])
        rate = float(row[rate_index])
        if not math.isfinite(rate):
            continue
        if previous is not None and timestamp < previous:
            raise ValueError(f"funding timestamps not monotonic in {path}")
        previous = timestamp
        records.append((timestamp, rate))
    if not records:
        raise ValueError(f"no funding rows in {path}")
    frame = pd.DataFrame(records, columns=["timestamp_ms", "funding_rate"]).drop_duplicates("timestamp_ms", keep="last")
    return frame.set_index("timestamp_ms").sort_index()


def load_day(
    session: requests.Session,
    cache: Path,
    symbol: str,
    date: str,
) -> DayData:
    source_records: list[SourceRecord] = []
    paths: dict[str, Path] = {}
    for data_type in ("aggTrades", "klines", "markPriceKlines", "fundingRate"):
        path, record = ensure_verified_archive(session, cache, symbol, data_type, date)
        paths[data_type] = path
        source_records.append(record)
    windows = load_agg_windows(paths["aggTrades"], date)
    contract = load_contract_klines(paths["klines"], date)
    mark = load_mark_klines(paths["markPriceKlines"], date)
    funding = load_funding(paths["fundingRate"])
    return DayData(symbol, date, windows, contract, mark, funding, source_records)


def source_manifest(records: Iterable[SourceRecord]) -> dict:
    items = [record.__dict__ for record in records]
    payload = json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    return {
        "records": items,
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
    }
