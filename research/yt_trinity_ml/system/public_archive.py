from __future__ import annotations

import calendar
import json
import time
from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Sequence

import pandas as pd
import requests

PUBLIC_ROOT = "https://public.bybit.com/kline_for_metatrader4"
SUPPORTED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
SUPPORTED_INTERVALS = (1, 5, 15, 30, 60)
COLUMNS = ("bar_start", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class ArchiveFileRecord:
    symbol: str
    interval_minutes: int
    month: str
    url: str
    local_path: str
    sha256: str
    compressed_bytes: int
    raw_row_count: int
    retained_row_count: int
    expected_row_count: int
    first_bar_start: str
    last_bar_start: str
    gap_count: int


@dataclass(frozen=True)
class ArchiveLoadResult:
    frame: pd.DataFrame
    records: tuple[ArchiveFileRecord, ...]


def utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        return result.tz_localize("UTC")
    return result.tz_convert("UTC")


def month_bounds(month: str | pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    value = utc_timestamp(month)
    start = pd.Timestamp(year=value.year, month=value.month, day=1, tz="UTC")
    return start, start + pd.offsets.MonthBegin(1)


def iter_months(start: str | pd.Timestamp, end_exclusive: str | pd.Timestamp) -> list[pd.Timestamp]:
    start_ts = utc_timestamp(start)
    end_ts = utc_timestamp(end_exclusive)
    if end_ts <= start_ts:
        raise ValueError("end_exclusive must be after start")
    first = start_ts.tz_localize(None).to_period("M")
    last = (end_ts - pd.Timedelta(nanoseconds=1)).tz_localize(None).to_period("M")
    return [period.to_timestamp().tz_localize("UTC") for period in pd.period_range(first, last, freq="M")]


def _validate_symbol(symbol: str) -> str:
    normalized = str(symbol).upper()
    if normalized not in SUPPORTED_SYMBOLS:
        raise ValueError(f"unsupported symbol: {symbol}")
    return normalized


def archive_filename(symbol: str, interval_minutes: int, month: str | pd.Timestamp) -> str:
    normalized = _validate_symbol(symbol)
    if interval_minutes not in SUPPORTED_INTERVALS:
        raise ValueError(f"unsupported interval: {interval_minutes}")
    month_ts = utc_timestamp(month)
    last_day = calendar.monthrange(month_ts.year, month_ts.month)[1]
    return (
        f"{normalized}_{interval_minutes}_{month_ts.year:04d}-{month_ts.month:02d}-01_"
        f"{month_ts.year:04d}-{month_ts.month:02d}-{last_day:02d}.csv.gz"
    )


def archive_url(symbol: str, interval_minutes: int, month: str | pd.Timestamp) -> str:
    normalized = _validate_symbol(symbol)
    month_ts = utc_timestamp(month)
    return f"{PUBLIC_ROOT}/{normalized}/{month_ts.year}/{archive_filename(normalized, interval_minutes, month_ts)}"


def _validate_ohlcv(frame: pd.DataFrame, interval_minutes: int) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("archive file contains no rows")
    result = frame.copy()
    result["bar_start"] = pd.to_datetime(result["bar_start"], format="%Y.%m.%d %H:%M", utc=True, errors="raise")
    for name in ("open", "high", "low", "close", "volume"):
        result[name] = pd.to_numeric(result[name], errors="raise")
    if result["bar_start"].duplicated().any():
        raise ValueError("duplicate bar_start in archive payload")
    if not result["bar_start"].is_monotonic_increasing:
        result = result.sort_values("bar_start", kind="stable")
    if (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("nonpositive price in archive")
    if (result["volume"] < 0).any():
        raise ValueError("negative volume in archive")
    if (result["high"] < result[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("invalid high in archive")
    if (result["low"] > result[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("invalid low in archive")

    delta = pd.Timedelta(minutes=interval_minutes)
    result["available_at"] = result["bar_start"] + delta
    bar_ns = pd.DatetimeIndex(result["bar_start"]).as_unit("ns").asi8
    available_ns = pd.DatetimeIndex(result["available_at"]).as_unit("ns").asi8
    result["start_time_ms"] = (bar_ns // 1_000_000).astype("int64")
    result["available_at_ms"] = (available_ns // 1_000_000).astype("int64")
    result["mark_close"] = result["close"]
    result["archive_interval_minutes"] = int(interval_minutes)
    return result.set_index("available_at", drop=False).sort_index()


def parse_archive_bytes(payload: bytes, interval_minutes: int) -> pd.DataFrame:
    if len(payload) < 2 or payload[:2] != b"\x1f\x8b":
        raise ValueError("payload is not gzip data")
    raw = pd.read_csv(BytesIO(payload), compression="gzip", header=None, names=list(COLUMNS))
    return _validate_ohlcv(raw, interval_minutes)


def parse_archive_file(path: str | Path, interval_minutes: int) -> pd.DataFrame:
    return parse_archive_bytes(Path(path).read_bytes(), interval_minutes)


def _download(
    session: requests.Session,
    url: str,
    target: Path,
    *,
    attempts: int,
    timeout_seconds: float,
) -> bytes:
    error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=timeout_seconds)
            response.raise_for_status()
            payload = response.content
            if not payload:
                raise RuntimeError("empty response body")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".partial")
            temporary.write_bytes(payload)
            temporary.replace(target)
            return payload
        except Exception as exc:  # noqa: BLE001 - the caller preserves the URL and final cause
            error = exc
            if attempt < attempts:
                time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
    raise RuntimeError(f"download failed after {attempts} attempts: {url}: {error}") from error


def _read_or_download(
    session: requests.Session,
    url: str,
    target: Path,
    *,
    interval_minutes: int,
    attempts: int,
    timeout_seconds: float,
) -> tuple[bytes, pd.DataFrame]:
    if target.exists():
        payload = target.read_bytes()
        try:
            return payload, parse_archive_bytes(payload, interval_minutes)
        except Exception:  # a corrupt cache must never become durable evidence
            target.unlink(missing_ok=True)
    payload = _download(session, url, target, attempts=attempts, timeout_seconds=timeout_seconds)
    return payload, parse_archive_bytes(payload, interval_minutes)


def load_public_archive(
    cache_root: str | Path,
    symbol: str,
    interval_minutes: int,
    start: str | pd.Timestamp,
    end_exclusive: str | pd.Timestamp,
    *,
    session: requests.Session | None = None,
    attempts: int = 4,
    timeout_seconds: float = 60.0,
) -> ArchiveLoadResult:
    normalized = _validate_symbol(symbol)
    if interval_minutes not in SUPPORTED_INTERVALS:
        raise ValueError(f"unsupported interval: {interval_minutes}")
    start_ts = utc_timestamp(start)
    end_ts = utc_timestamp(end_exclusive)
    if end_ts <= start_ts:
        raise ValueError("end_exclusive must be after start")
    cache_root = Path(cache_root)
    own_session = session is None
    session = session or requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-causal-research/1.0"})
    frames: list[pd.DataFrame] = []
    records: list[ArchiveFileRecord] = []
    try:
        for month in iter_months(start_ts, end_ts):
            month_start, next_month = month_bounds(month)
            filename = archive_filename(normalized, interval_minutes, month)
            target = cache_root / "bybit_public_mt4" / normalized / str(month.year) / filename
            url = archive_url(normalized, interval_minutes, month)
            payload, raw_frame = _read_or_download(
                session,
                url,
                target,
                interval_minutes=interval_minutes,
                attempts=attempts,
                timeout_seconds=timeout_seconds,
            )
            # Bybit monthly archives include the first bar of the following month.
            # Retain the named month only so adjacent files cannot duplicate a bar.
            frame = raw_frame[(raw_frame["bar_start"] >= month_start) & (raw_frame["bar_start"] < next_month)].copy()
            if frame.empty:
                raise RuntimeError(f"archive month has no retained bars: {url}")
            expected_delta = pd.Timedelta(minutes=interval_minutes)
            gaps = int((frame["bar_start"].diff().dropna() > expected_delta).sum())
            expected_rows = int((next_month - month_start) / expected_delta)
            records.append(
                ArchiveFileRecord(
                    symbol=normalized,
                    interval_minutes=interval_minutes,
                    month=month.strftime("%Y-%m"),
                    url=url,
                    local_path=str(target),
                    sha256=sha256(payload).hexdigest(),
                    compressed_bytes=len(payload),
                    raw_row_count=len(raw_frame),
                    retained_row_count=len(frame),
                    expected_row_count=expected_rows,
                    first_bar_start=frame["bar_start"].iloc[0].isoformat(),
                    last_bar_start=frame["bar_start"].iloc[-1].isoformat(),
                    gap_count=gaps,
                )
            )
            frames.append(frame)
    finally:
        if own_session:
            session.close()

    combined = pd.concat(frames, axis=0).sort_values("bar_start", kind="stable")
    combined = combined[(combined["bar_start"] >= start_ts) & (combined["bar_start"] < end_ts)].copy()
    if combined.empty:
        raise RuntimeError(f"no bars after slicing {normalized} {start_ts}..{end_ts}")
    if combined["bar_start"].duplicated().any() or combined.index.duplicated().any():
        raise RuntimeError("duplicate bars across archive files")
    if not (combined.index >= combined["bar_start"]).all():
        raise RuntimeError("bar available before bar_start")
    if not combined.index.is_monotonic_increasing:
        raise RuntimeError("archive availability index is not monotonic")
    return ArchiveLoadResult(combined, tuple(records))


def build_frames(
    cache_root: str | Path,
    symbols: Sequence[str],
    start: str | pd.Timestamp,
    end_exclusive: str | pd.Timestamp,
    *,
    execution_interval_minutes: int = 1,
    decision_interval_minutes: int = 5,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, object]]:
    normalized_symbols = tuple(_validate_symbol(symbol) for symbol in symbols)
    if len(set(normalized_symbols)) != len(normalized_symbols):
        raise ValueError("symbols must be unique")
    execution: dict[str, pd.DataFrame] = {}
    decision: dict[str, pd.DataFrame] = {}
    records: list[ArchiveFileRecord] = []
    with requests.Session() as session:
        session.headers.update({"User-Agent": "SMC-ICT-causal-research/1.0"})
        for symbol in normalized_symbols:
            execution_result = load_public_archive(
                cache_root,
                symbol,
                execution_interval_minutes,
                start,
                end_exclusive,
                session=session,
            )
            if decision_interval_minutes == execution_interval_minutes:
                decision_result = execution_result
            else:
                decision_result = load_public_archive(
                    cache_root,
                    symbol,
                    decision_interval_minutes,
                    start,
                    end_exclusive,
                    session=session,
                )
            execution[symbol] = execution_result.frame
            decision[symbol] = decision_result.frame
            records.extend(execution_result.records)
            if decision_result is not execution_result:
                records.extend(decision_result.records)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "source": PUBLIC_ROOT,
        "source_product": "Bybit public MetaTrader4 USDT perpetual kline archive",
        "start": utc_timestamp(start).isoformat(),
        "end_exclusive": utc_timestamp(end_exclusive).isoformat(),
        "symbols": list(normalized_symbols),
        "execution_interval_minutes": execution_interval_minutes,
        "decision_interval_minutes": decision_interval_minutes,
        "records": [asdict(record) for record in records],
        "limitations": {
            "bid_ask": "not present; coarse executor applies configured minimum spread and slippage",
            "mark_price": "trade close is used only as a coarse mark proxy",
            "funding": "not present; the result is never rankable until timestamped funding is joined",
            "partial_fill": "not observable; passive trade-through and a later event-tape gate remain required",
        },
    }
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest["manifest_sha256"] = sha256(canonical.encode("utf-8")).hexdigest()
    return decision, execution, manifest


def write_manifest(path: str | Path, manifest: dict[str, object]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
