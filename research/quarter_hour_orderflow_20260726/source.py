from __future__ import annotations

import csv
import hashlib
import json
import math
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np
import pandas as pd
import requests

BASE = "https://data.binance.vision/data/futures/um"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
DAY_MS = 86_400_000
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
class DayBundle:
    symbol: str
    date: str
    windows: pd.DataFrame
    contract: pd.DataFrame
    mark: pd.DataFrame
    metrics: pd.DataFrame
    funding: pd.DataFrame
    source_records: list[SourceRecord]


def utc_day_start_ms(date: str) -> int:
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1_000)


def add_days(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def normalize_timestamp_ms(raw: str | int | float) -> int:
    text = str(raw).strip()
    try:
        value = int(float(text))
    except ValueError:
        parsed = pd.Timestamp(text)
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize("UTC")
        else:
            parsed = parsed.tz_convert("UTC")
        return int(parsed.timestamp() * 1_000)
    if value >= 10**17:
        return value // 1_000_000
    if value >= 10**14:
        return value // 1_000
    if value >= 10**11:
        return value
    return value * 1_000


def archive_urls(symbol: str, data_type: str, date: str) -> tuple[str, str, str]:
    if data_type == "aggTrades":
        name = f"{symbol}-aggTrades-{date}.zip"
        url = f"{BASE}/daily/aggTrades/{symbol}/{name}"
        partition = date
    elif data_type == "klines":
        name = f"{symbol}-1m-{date}.zip"
        url = f"{BASE}/daily/klines/{symbol}/1m/{name}"
        partition = date
    elif data_type == "markPriceKlines":
        name = f"{symbol}-1m-{date}.zip"
        url = f"{BASE}/daily/markPriceKlines/{symbol}/1m/{name}"
        partition = date
    elif data_type == "metrics":
        name = f"{symbol}-metrics-{date}.zip"
        url = f"{BASE}/daily/metrics/{symbol}/{name}"
        partition = date
    elif data_type == "fundingRate":
        month = date[:7]
        name = f"{symbol}-fundingRate-{month}.zip"
        url = f"{BASE}/monthly/fundingRate/{symbol}/{name}"
        partition = month
    else:
        raise ValueError(f"unsupported data type: {data_type}")
    return url, f"{url}.CHECKSUM", partition


def _download(
    session: requests.Session,
    url: str,
    target: Path,
    *,
    attempts: int = 5,
) -> tuple[bytes, bool]:
    cache_hit = target.exists() and target.stat().st_size > 0
    if cache_hit:
        return target.read_bytes(), True
    target.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=(30, 600))
            if response.status_code == 200:
                target.write_bytes(response.content)
                return response.content, False
            errors.append(f"HTTP {response.status_code}")
            if response.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(2**attempt, 12))
    raise RuntimeError(f"download failed {url}: {'; '.join(errors[-5:])}")


def parse_expected_checksum(payload: bytes) -> str:
    token = payload.decode("utf-8", errors="replace").strip().split()[0].lower()
    if len(token) != 64 or any(char not in "0123456789abcdef" for char in token):
        raise ValueError("invalid adjacent CHECKSUM payload")
    return token


def ensure_verified_archive(
    session: requests.Session,
    cache: Path,
    symbol: str,
    data_type: str,
    date: str,
) -> tuple[Path, SourceRecord]:
    url, checksum_url, partition = archive_urls(symbol, data_type, date)
    target = cache / data_type / symbol / Path(url).name
    checksum_target = cache / data_type / symbol / Path(checksum_url).name
    payload, cache_hit = _download(session, url, target)
    checksum_payload, _ = _download(session, checksum_url, checksum_target)
    observed = hashlib.sha256(payload).hexdigest()
    expected = parse_expected_checksum(checksum_payload)
    if observed != expected:
        raise ValueError(f"checksum mismatch {url}: observed={observed} expected={expected}")
    with zipfile.ZipFile(target) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        if len(members) != 1:
            raise ValueError(f"expected one CSV member in {target}, got {members}")
        if archive.getinfo(members[0]).file_size <= 0:
            raise ValueError(f"empty CSV member in {target}")
    return target, SourceRecord(
        symbol=symbol,
        data_type=data_type,
        partition=partition,
        url=url,
        checksum_url=checksum_url,
        bytes=len(payload),
        sha256=observed,
        expected_sha256=expected,
        cache_hit=cache_hit,
    )


def _is_header(row: list[str]) -> bool:
    if not row:
        return False
    try:
        float(row[0])
    except (TypeError, ValueError):
        return True
    return False


def csv_rows(path: Path) -> Iterator[list[str]]:
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
            if _is_header(first):
                yield [item.strip() for item in first]
                yield from reader
            else:
                yield [f"c{index}" for index in range(len(first))]
                yield first
                yield from reader


def _boolean(raw: str) -> bool:
    return raw.strip().lower() in {"true", "1", "t", "yes"}


def load_agg_windows(path: Path, date: str) -> pd.DataFrame:
    start = utc_day_start_ms(date)
    end = start + DAY_MS
    accumulators: dict[tuple[str, int], dict[str, float | int]] = {}
    rows = iter(csv_rows(path))
    header = next(rows)
    if len(header) < 7:
        raise ValueError(f"aggTrades width below seven: {header}")
    for row in rows:
        if len(row) < 7:
            raise ValueError(f"short aggTrades row in {path}: {row}")
        timestamp = normalize_timestamp_ms(row[5])
        if timestamp < start or timestamp >= end:
            continue
        quarter_start = timestamp // QUARTER_MS * QUARTER_MS
        delta = timestamp - quarter_start
        if 0 <= delta < WINDOW_MS:
            phase, event_start = "quarter", quarter_start
        elif CONTROL_OFFSET_MS <= delta < CONTROL_OFFSET_MS + WINDOW_MS:
            phase, event_start = "control", quarter_start + CONTROL_OFFSET_MS
        else:
            continue
        price = float(row[1])
        quantity = float(row[2])
        if not (math.isfinite(price) and price > 0 and math.isfinite(quantity) and quantity > 0):
            continue
        notional = price * quantity
        signed = -notional if _boolean(row[6]) else notional
        key = (phase, event_start)
        item = accumulators.get(key)
        if item is None:
            accumulators[key] = {
                "first_price": price,
                "last_price": price,
                "high_price": price,
                "low_price": price,
                "total_notional": notional,
                "signed_notional": signed,
                "trade_count": 1,
                "first_trade_ms": timestamp,
                "last_trade_ms": timestamp,
            }
        else:
            item["last_price"] = price
            item["high_price"] = max(float(item["high_price"]), price)
            item["low_price"] = min(float(item["low_price"]), price)
            item["total_notional"] = float(item["total_notional"]) + notional
            item["signed_notional"] = float(item["signed_notional"]) + signed
            item["trade_count"] = int(item["trade_count"]) + 1
            item["last_trade_ms"] = timestamp

    output: list[dict[str, float | int | bool | str]] = []
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
                    "high_price": np.nan,
                    "low_price": np.nan,
                    "opening_return": np.nan,
                    "opening_range_bps": np.nan,
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
            high_price = float(item["high_price"])
            low_price = float(item["low_price"])
            output.append({
                "phase": phase,
                "event_start_ms": event_start,
                "decision_ms": event_start + WINDOW_MS,
                "first_price": first_price,
                "last_price": last_price,
                "high_price": high_price,
                "low_price": low_price,
                "opening_return": math.log(last_price / first_price),
                "opening_range_bps": 10_000.0 * (high_price - low_price) / first_price,
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


def load_kline(path: Path, date: str, *, contract: bool) -> pd.DataFrame:
    start = utc_day_start_ms(date)
    expected = np.arange(start, start + DAY_MS, MINUTE_MS, dtype=np.int64)
    rows = iter(csv_rows(path))
    _ = next(rows)
    records: list[dict[str, float | int]] = []
    for row in rows:
        if len(row) < 5:
            raise ValueError(f"short kline row in {path}: {row}")
        open_ms = normalize_timestamp_ms(row[0])
        if open_ms < start or open_ms >= start + DAY_MS:
            continue
        values = [float(row[index]) for index in (1, 2, 3, 4)]
        if not all(math.isfinite(value) and value > 0 for value in values):
            continue
        record: dict[str, float | int] = {
            "open_ms": open_ms,
            "open": values[0],
            "high": values[1],
            "low": values[2],
            "close": values[3],
        }
        if contract:
            if len(row) < 11:
                raise ValueError(f"contract kline lacks volume fields: {row}")
            quote_volume = float(row[7])
            taker_buy_quote = float(row[10])
            record["quote_volume"] = quote_volume
            record["taker_buy_quote"] = taker_buy_quote
        records.append(record)
    frame = pd.DataFrame(records)
    if frame.empty:
        frame = pd.DataFrame(index=expected)
    else:
        if frame.open_ms.duplicated().any():
            raise ValueError(f"duplicate kline open times in {path}")
        frame = frame.set_index("open_ms").sort_index().reindex(expected)
    required = ["open", "high", "low", "close"] + (["quote_volume", "taker_buy_quote"] if contract else [])
    for column in required:
        if column not in frame:
            frame[column] = np.nan
    frame["valid"] = np.isfinite(frame[required].to_numpy(float)).all(axis=1)
    frame.index.name = "open_ms"
    return frame


def _normalized_header(header: list[str]) -> dict[str, int]:
    return {
        item.strip().lower().replace(" ", "_").replace("-", "_"): index
        for index, item in enumerate(header)
    }


def _pick(mapping: dict[str, int], candidates: tuple[str, ...], default: int | None = None) -> int:
    for name in candidates:
        if name in mapping:
            return mapping[name]
    if default is None:
        raise ValueError(f"missing required columns {candidates}; got {sorted(mapping)}")
    return default


def load_metrics(path: Path, date: str) -> pd.DataFrame:
    start = utc_day_start_ms(date)
    rows = iter(csv_rows(path))
    header = next(rows)
    mapping = _normalized_header(header)
    time_idx = _pick(mapping, ("create_time", "timestamp", "time", "calc_time"), 0)
    oi_idx = _pick(mapping, ("sum_open_interest", "open_interest"))
    oi_value_idx = _pick(mapping, ("sum_open_interest_value", "open_interest_value"), oi_idx)
    taker_idx = _pick(mapping, ("sum_taker_long_short_vol_ratio", "taker_long_short_ratio"))
    top_idx = _pick(mapping, ("sum_toptrader_long_short_ratio", "toptrader_long_short_ratio"))
    records: list[dict[str, float | int]] = []
    for row in rows:
        if max(time_idx, oi_idx, oi_value_idx, taker_idx, top_idx) >= len(row):
            continue
        timestamp = normalize_timestamp_ms(row[time_idx])
        if timestamp < start or timestamp >= start + DAY_MS:
            continue
        try:
            values = [float(row[index]) for index in (oi_idx, oi_value_idx, taker_idx, top_idx)]
        except ValueError:
            continue
        if not all(math.isfinite(value) and value > 0 for value in values):
            continue
        records.append({
            "timestamp_ms": timestamp,
            "open_interest": values[0],
            "open_interest_value": values[1],
            "taker_long_short_ratio": values[2],
            "toptrader_long_short_ratio": values[3],
        })
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError(f"no usable metrics rows in {path}")
    if frame.timestamp_ms.duplicated().any():
        frame = frame.drop_duplicates("timestamp_ms", keep="last")
    return frame.set_index("timestamp_ms").sort_index()


def load_funding(path: Path) -> pd.DataFrame:
    rows = iter(csv_rows(path))
    header = next(rows)
    mapping = _normalized_header(header)
    time_idx = _pick(mapping, ("calc_time", "funding_time", "fundingtime", "time", "timestamp"), 0)
    rate_idx = _pick(mapping, ("last_funding_rate", "funding_rate", "fundingrate", "rate"), len(header) - 1)
    records: list[tuple[int, float]] = []
    for row in rows:
        if max(time_idx, rate_idx) >= len(row):
            continue
        try:
            timestamp = normalize_timestamp_ms(row[time_idx])
            rate = float(row[rate_idx])
        except ValueError:
            continue
        if math.isfinite(rate):
            records.append((timestamp, rate))
    if not records:
        raise ValueError(f"no funding rows in {path}")
    frame = pd.DataFrame(records, columns=["timestamp_ms", "funding_rate"])
    return frame.drop_duplicates("timestamp_ms", keep="last").set_index("timestamp_ms").sort_index()


def _concat_unique(frames: list[pd.DataFrame]) -> pd.DataFrame:
    frame = pd.concat(frames).sort_index()
    if frame.index.duplicated().any():
        frame = frame[~frame.index.duplicated(keep="last")]
    return frame


def load_bundle(
    session: requests.Session,
    cache: Path,
    symbol: str,
    date: str,
    *,
    tail_days: int = 3,
) -> DayBundle:
    records: list[SourceRecord] = []

    agg_path, record = ensure_verified_archive(session, cache, symbol, "aggTrades", date)
    records.append(record)
    metrics_path, record = ensure_verified_archive(session, cache, symbol, "metrics", date)
    records.append(record)
    windows = load_agg_windows(agg_path, date)
    metrics = load_metrics(metrics_path, date)

    contract_frames: list[pd.DataFrame] = []
    mark_frames: list[pd.DataFrame] = []
    for offset in range(tail_days + 1):
        partition = add_days(date, offset)
        contract_path, record = ensure_verified_archive(session, cache, symbol, "klines", partition)
        records.append(record)
        mark_path, record = ensure_verified_archive(session, cache, symbol, "markPriceKlines", partition)
        records.append(record)
        contract_frames.append(load_kline(contract_path, partition, contract=True))
        mark_frames.append(load_kline(mark_path, partition, contract=False))

    funding_path, record = ensure_verified_archive(session, cache, symbol, "fundingRate", date)
    records.append(record)
    funding = load_funding(funding_path)

    return DayBundle(
        symbol=symbol,
        date=date,
        windows=windows,
        contract=_concat_unique(contract_frames),
        mark=_concat_unique(mark_frames),
        metrics=metrics,
        funding=funding,
        source_records=records,
    )


def load_bundles(
    dates: Iterable[str],
    symbols: Iterable[str],
    cache: Path,
    *,
    tail_days: int = 3,
) -> tuple[list[DayBundle], list[SourceRecord]]:
    bundles: list[DayBundle] = []
    records: list[SourceRecord] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-qhour-structural-ml/2.0"
        for date in dates:
            for symbol in symbols:
                print(f"loading {date} {symbol}", flush=True)
                bundle = load_bundle(session, cache, symbol, date, tail_days=tail_days)
                bundles.append(bundle)
                records.extend(bundle.source_records)
    return bundles, records


def source_manifest(records: Iterable[SourceRecord]) -> dict:
    deduplicated: dict[tuple[str, str, str], dict] = {}
    for record in records:
        deduplicated[(record.symbol, record.data_type, record.partition)] = asdict(record)
    items = [deduplicated[key] for key in sorted(deduplicated)]
    payload = json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    return {
        "record_count": len(items),
        "records": items,
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "all_checksums_match": all(item["sha256"] == item["expected_sha256"] for item in items),
    }
