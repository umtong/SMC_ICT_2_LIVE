from __future__ import annotations

import argparse
import hashlib
import io
import itertools
import json
import math
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
PREREG_PATH = ROOT / "preregistration.json"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
BINANCE_ROOT = "https://data.binance.vision/data/futures/um"
NY = ZoneInfo("America/New_York")
ATR_BARS = 96
PERIODS = {
    "fit": (pd.Timestamp("2021-01-01T00:00:00Z"), pd.Timestamp("2021-12-31T23:59:59Z")),
    "development": (pd.Timestamp("2022-01-01T00:00:00Z"), pd.Timestamp("2022-12-31T23:59:59Z")),
    "confirmation": (pd.Timestamp("2023-01-01T00:00:00Z"), pd.Timestamp("2023-12-31T23:59:59Z")),
}
CME_TO_EXECUTION = {"BTC=F": "BTCUSDT", "ETH=F": "ETHUSDT"}
KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_base_volume",
    "taker_buy_quote_volume", "ignore",
]
FUNDING_COLUMNS = ["calc_time", "funding_interval_hours", "last_funding_rate"]
COSTS = (12, 18, 24)


@dataclass(frozen=True, slots=True)
class Config:
    family: str
    gap_kind: str
    gap_quantile: float
    max_residual_bps: float
    confirmation_bars: int
    stop_buffer_atr: float
    trigger: str | None = None
    body_atr: float | None = None
    target_kind: str | None = None

    @property
    def config_id(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class GapEvent:
    symbol: str
    cme_symbol: str
    trading_date: str
    previous_trading_date: str
    gap_kind: str
    open_ts: pd.Timestamp
    prior_close_ts: pd.Timestamp
    cme_open: float
    cme_prior_close: float
    gap_return_bps: float
    crypto_halt_return_bps: float
    roll_residual_bps: float
    execution_open: float
    mapped_prior_close: float
    gap_low: float
    gap_high: float
    gap_ce: float
    atr: float
    previous_day_high: float
    previous_day_low: float
    previous_week_high: float
    previous_week_low: float


@dataclass(frozen=True, slots=True)
class Setup:
    config_id: str
    family: str
    symbol: str
    gap_kind: str
    trading_date: str
    side: int
    event_open_ts: pd.Timestamp
    confirmation_end_ts: pd.Timestamp
    entry_ts: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    score: float
    gap_return_bps: float
    roll_residual_bps: float


@dataclass(frozen=True, slots=True)
class Trade:
    config_id: str
    family: str
    symbol: str
    gap_kind: str
    trading_date: str
    side: int
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    price_bps: float
    funding_bps: float
    gross_bps: float
    exit_reason: str
    score: float


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def request_bytes(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    allow_not_found: bool = False,
    attempts: int = 6,
) -> tuple[bytes, dict[str, Any]] | None:
    errors: list[str] = []
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=(30, 300))
            metadata = {
                "requested_url": response.url,
                "http_status": int(response.status_code),
                "content_type": response.headers.get("Content-Type"),
                "content_length_header": response.headers.get("Content-Length"),
            }
            if response.status_code == 200:
                return response.content, metadata
            if response.status_code == 404 and allow_not_found:
                return None
            errors.append(f"HTTP {response.status_code}: {response.text[:200]}")
            if response.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(0.5 * 2**attempt, 8.0))
    raise RuntimeError(f"request failed {url}: {' | '.join(errors[-6:])}")


def parse_checksum(payload: bytes) -> str:
    text = payload.decode("utf-8-sig").strip()
    token = text.split()[0] if text else ""
    if len(token) != 64 or any(char not in "0123456789abcdefABCDEF" for char in token):
        raise ValueError(f"invalid checksum payload: {text[:120]!r}")
    return token.lower()


def month_labels(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return [str(item) for item in pd.period_range(start=start, end=end, freq="M")]


def get_archive(
    session: requests.Session,
    cache: Path,
    url: str,
    *,
    allow_not_found: bool = False,
) -> tuple[bytes, dict[str, Any]] | None:
    cache.mkdir(parents=True, exist_ok=True)
    name = url.rsplit("/", 1)[-1]
    target = cache / name
    checksum_target = cache / f"{name}.CHECKSUM"
    cache_hit = target.exists() and checksum_target.exists()
    if cache_hit:
        payload = target.read_bytes()
        checksum_payload = checksum_target.read_bytes()
        transport = {"requested_url": url, "http_status": 200}
        checksum_transport = {"requested_url": url + ".CHECKSUM", "http_status": 200}
    else:
        loaded = request_bytes(session, url, allow_not_found=allow_not_found)
        if loaded is None:
            return None
        payload, transport = loaded
        checksum_loaded = request_bytes(session, url + ".CHECKSUM")
        assert checksum_loaded is not None
        checksum_payload, checksum_transport = checksum_loaded
        target.write_bytes(payload)
        checksum_target.write_bytes(checksum_payload)
    expected = parse_checksum(checksum_payload)
    actual = sha256(payload)
    if actual != expected:
        raise ValueError(f"checksum mismatch {url}: expected={expected} actual={actual}")
    return payload, {
        "url": transport["requested_url"],
        "http_status": transport["http_status"],
        "bytes": len(payload),
        "sha256": actual,
        "checksum_url": checksum_transport["requested_url"],
        "checksum_http_status": checksum_transport["http_status"],
        "checksum_payload_sha256": sha256(checksum_payload),
        "checksum_verified": True,
        "cache_hit": cache_hit,
    }


def csv_from_zip(payload: bytes, columns: list[str]) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in archive, found {names}")
        raw = archive.read(names[0])
    frame = pd.read_csv(io.BytesIO(raw), header=None, dtype=str)
    if frame.empty:
        return pd.DataFrame(columns=columns)
    first = str(frame.iloc[0, 0]).strip().lower()
    if first in {columns[0].lower(), "open_time", "calc_time"}:
        frame = frame.iloc[1:].reset_index(drop=True)
    if frame.shape[1] < len(columns):
        raise ValueError(f"archive CSV has {frame.shape[1]} columns, expected at least {len(columns)}")
    frame = frame.iloc[:, :len(columns)].copy()
    frame.columns = columns
    return frame


def parse_epoch(values: pd.Series) -> pd.DatetimeIndex:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric.dropna()
    if finite.empty:
        return pd.DatetimeIndex([pd.NaT] * len(numeric), tz="UTC")
    unit = "us" if float(finite.median()) >= 1e14 else "ms"
    return pd.DatetimeIndex(pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce"))


def yahoo_period_seconds(start: pd.Timestamp, end: pd.Timestamp) -> tuple[int, int]:
    return int(start.timestamp()), int((end + pd.Timedelta(seconds=1)).timestamp())


def load_cme_daily(
    session: requests.Session,
    cache: Path,
    cme_symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    start_s, end_s = yahoo_period_seconds(start, end)
    key = f"{cme_symbol.replace('=', '_')}_{start.date()}_{end.date()}"
    root = cache / "yahoo_cme"
    raw_path = root / f"{key}.json"
    normalized_path = root / f"{key}.csv"
    manifest_path = root / f"{key}.manifest.json"
    if raw_path.exists() and normalized_path.exists() and manifest_path.exists():
        frame = pd.read_csv(normalized_path, parse_dates=["timestamp"])
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["cache_hit"] = True
        return frame.set_index("date").sort_index(), manifest

    url = YAHOO.format(symbol=quote(cme_symbol, safe=""))
    loaded = request_bytes(session, url, params={
        "period1": start_s,
        "period2": end_s,
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    })
    assert loaded is not None
    payload, transport = loaded
    decoded = json.loads(payload)
    chart = decoded.get("chart", {})
    if chart.get("error"):
        raise ValueError(f"Yahoo error {cme_symbol}: {chart['error']}")
    results = chart.get("result") or []
    if len(results) != 1:
        raise ValueError(f"Yahoo result count {cme_symbol}: {len(results)}")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quote_blocks = (result.get("indicators") or {}).get("quote") or []
    if len(quote_blocks) != 1:
        raise ValueError(f"Yahoo quote block missing {cme_symbol}")
    quote_data = quote_blocks[0]
    rows: list[dict[str, Any]] = []
    for index, raw_ts in enumerate(timestamps):
        row = {"timestamp": pd.Timestamp(int(raw_ts), unit="s", tz="UTC")}
        for name in ("open", "high", "low", "close", "volume"):
            values = quote_data.get(name) or []
            row[name] = values[index] if index < len(values) else None
        try:
            prices = [float(row[name]) for name in ("open", "high", "low", "close")]
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) and value > 0 for value in prices):
            continue
        row.update({name: float(row[name]) for name in ("open", "high", "low", "close")})
        row["volume"] = float(row["volume"]) if row["volume"] is not None else 0.0
        row["date"] = row["timestamp"].date()
        rows.append(row)
    frame = pd.DataFrame(rows).drop_duplicates("date", keep="last").sort_values("date")
    if frame.empty:
        raise ValueError(f"Yahoo returned no finite rows for {cme_symbol}")
    root.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(payload)
    frame.to_csv(normalized_path, index=False)
    meta = result.get("meta") or {}
    manifest = {
        "kind": "yahoo_cme_continuous_daily",
        "cme_symbol": cme_symbol,
        "requested_start": str(start),
        "requested_end": str(end),
        "requested_url": transport["requested_url"],
        "http_status": transport["http_status"],
        "retrieved_bytes": len(payload),
        "raw_sha256": sha256(payload),
        "normalized_sha256": sha256(normalized_path.read_bytes()),
        "row_count": int(len(frame)),
        "first_date": str(frame.iloc[0]["date"]),
        "last_date": str(frame.iloc[-1]["date"]),
        "exchange_name": meta.get("exchangeName"),
        "exchange_timezone_name": meta.get("exchangeTimezoneName"),
        "instrument_type": meta.get("instrumentType"),
        "currency": meta.get("currency"),
        "strictly_chronological": bool(frame["date"].is_monotonic_increasing),
        "cache_hit": False,
    }
    write_json(manifest_path, manifest)
    return frame.set_index("date").sort_index(), manifest


def kline_url(symbol: str, label: str, *, daily: bool = False) -> str:
    periodicity = "daily" if daily else "monthly"
    return f"{BINANCE_ROOT}/{periodicity}/klines/{symbol}/15m/{symbol}-15m-{label}.zip"


def funding_url(symbol: str, label: str) -> str:
    return f"{BINANCE_ROOT}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{label}.zip"


def normalize_klines(parts: list[pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=KLINE_COLUMNS)
    frame["timestamp"] = parse_epoch(frame["open_time"])
    for name in ("open", "high", "low", "close", "volume", "quote_volume"):
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    frame = frame.rename(columns={"quote_volume": "turnover"})
    frame = frame[["timestamp", "open", "high", "low", "close", "volume", "turnover"]]
    frame = frame.dropna().drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    frame = frame.loc[(frame["timestamp"] >= start) & (frame["timestamp"] <= end)].set_index("timestamp")
    return frame


def load_klines(
    session: requests.Session,
    cache: Path,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = f"{symbol}_{start.date()}_{end.date()}"
    root = cache / "binance_usdm" / "klines" / symbol
    target = root / f"{key}.csv"
    manifest_path = root / f"{key}.manifest.json"
    if target.exists() and manifest_path.exists():
        frame = pd.read_csv(target, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["cache_hit"] = True
        return frame, manifest

    parts: list[pd.DataFrame] = []
    pages: list[dict[str, Any]] = []
    for label in month_labels(start, end):
        url = kline_url(symbol, label)
        loaded = get_archive(session, root / "archives", url)
        assert loaded is not None
        payload, record = loaded
        parsed = csv_from_zip(payload, KLINE_COLUMNS)
        record.update({"periodicity": "monthly", "label": label, "returned_rows": int(len(parsed))})
        pages.append(record)
        parts.append(parsed)

    frame = normalize_klines(parts, start, end)
    expected = pd.date_range(start=start.ceil("15min"), end=end.floor("15min"), freq="15min")
    missing_before = expected.difference(frame.index)
    missing_dates = sorted({str(value.date()) for value in missing_before})
    if len(missing_dates) > 60:
        raise RuntimeError(f"too many missing Binance kline dates for {symbol}: {len(missing_dates)}")
    repairs: list[pd.DataFrame] = []
    for label in missing_dates:
        url = kline_url(symbol, label, daily=True)
        loaded = get_archive(session, root / "daily_repairs", url, allow_not_found=True)
        if loaded is None:
            pages.append({
                "url": url,
                "periodicity": "daily_repair",
                "label": label,
                "not_found": True,
                "bytes": 0,
                "sha256": sha256(b""),
                "returned_rows": 0,
            })
            continue
        payload, record = loaded
        parsed = csv_from_zip(payload, KLINE_COLUMNS)
        record.update({"periodicity": "daily_repair", "label": label, "returned_rows": int(len(parsed))})
        pages.append(record)
        repairs.append(parsed)
    if repairs:
        frame = normalize_klines(parts + repairs, start, end)
    if frame.empty:
        raise RuntimeError(f"no Binance kline rows for {symbol}")
    if frame.index.max() >= pd.Timestamp("2024-01-01T00:00:00Z"):
        raise AssertionError("official 2024 execution data opened")
    root.mkdir(parents=True, exist_ok=True)
    frame.reset_index().to_csv(target, index=False)
    missing_after = expected.difference(frame.index)
    manifest = {
        "kind": "binance_usdm_kline_proxy",
        "symbol": symbol,
        "start": str(start),
        "end": str(end),
        "page_count": len(pages),
        "pages": pages,
        "row_count": int(len(frame)),
        "normalized_sha256": sha256(target.read_bytes()),
        "first_timestamp": str(frame.index.min()),
        "last_timestamp": str(frame.index.max()),
        "missing_bar_count_before_daily_repair": int(len(missing_before)),
        "missing_bar_count_after_daily_repair": int(len(missing_after)),
        "missing_bar_fraction_after_daily_repair": float(len(missing_after) / max(len(expected), 1)),
        "cache_hit": False,
    }
    write_json(manifest_path, manifest)
    return frame, manifest


def normalize_funding(parts: list[pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=FUNDING_COLUMNS)
    frame["timestamp"] = parse_epoch(frame["calc_time"])
    frame["rate"] = pd.to_numeric(frame["last_funding_rate"], errors="coerce")
    frame = frame[["timestamp", "rate"]].dropna().drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    frame = frame.loc[(frame["timestamp"] >= start) & (frame["timestamp"] <= end)]
    return frame.set_index("timestamp")["rate"].astype(float)


def load_funding(
    session: requests.Session,
    cache: Path,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.Series, dict[str, Any]]:
    key = f"{symbol}_{start.date()}_{end.date()}"
    root = cache / "binance_usdm" / "funding" / symbol
    target = root / f"{key}.csv"
    manifest_path = root / f"{key}.manifest.json"
    if target.exists() and manifest_path.exists():
        frame = pd.read_csv(target, parse_dates=["timestamp"])
        series = frame.set_index("timestamp")["rate"].sort_index().astype(float)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["cache_hit"] = True
        return series, manifest

    parts: list[pd.DataFrame] = []
    pages: list[dict[str, Any]] = []
    for label in month_labels(start, end):
        url = funding_url(symbol, label)
        loaded = get_archive(session, root / "archives", url)
        assert loaded is not None
        payload, record = loaded
        parsed = csv_from_zip(payload, FUNDING_COLUMNS)
        record.update({"label": label, "returned_rows": int(len(parsed))})
        pages.append(record)
        parts.append(parsed)
    series = normalize_funding(parts, start, end)
    if series.empty:
        raise RuntimeError(f"no Binance funding rows for {symbol}")
    if series.index.max() >= pd.Timestamp("2024-01-01T00:00:00Z"):
        raise AssertionError("official 2024 funding data opened")
    root.mkdir(parents=True, exist_ok=True)
    series.rename("rate").reset_index().to_csv(target, index=False)
    manifest = {
        "kind": "binance_usdm_funding_proxy",
        "symbol": symbol,
        "start": str(start),
        "end": str(end),
        "page_count": len(pages),
        "pages": pages,
        "row_count": int(len(series)),
        "normalized_sha256": sha256(target.read_bytes()),
        "first_timestamp": str(series.index.min()),
        "last_timestamp": str(series.index.max()),
        "cache_hit": False,
    }
    write_json(manifest_path, manifest)
    return series, manifest


def config_grid() -> list[Config]:
    configs: list[Config] = []
    for gap_kind, gap_quantile, residual, bars, stop_buffer, trigger in itertools.product(
        ("NDOG", "NWOG", "BOTH"),
        (0.5, 0.75, 0.9),
        (15.0, 35.0),
        (1, 2),
        (0.0, 0.1),
        ("consequent_encroachment", "three_quarter_depth"),
    ):
        configs.append(Config(
            family="gap_rebalance",
            gap_kind=gap_kind,
            gap_quantile=gap_quantile,
            max_residual_bps=residual,
            confirmation_bars=bars,
            stop_buffer_atr=stop_buffer,
            trigger=trigger,
        ))
    for gap_kind, gap_quantile, residual, bars, stop_buffer, body_atr, target_kind in itertools.product(
        ("NDOG", "NWOG", "BOTH"),
        (0.5, 0.75, 0.9),
        (15.0, 35.0),
        (1, 2),
        (0.0, 0.1),
        (0.25, 0.75),
        ("previous_day", "previous_week"),
    ):
        configs.append(Config(
            family="gap_acceptance",
            gap_kind=gap_kind,
            gap_quantile=gap_quantile,
            max_residual_bps=residual,
            confirmation_bars=bars,
            stop_buffer_atr=stop_buffer,
            body_atr=body_atr,
            target_kind=target_kind,
        ))
    if len(configs) != 432 or len({config.config_id for config in configs}) != 432:
        raise AssertionError("frozen candidate grid is not exactly 432 unique policies")
    return configs


def final_business_days(year: int, month: int, count: int = 5) -> set[pd.Timestamp.date]:
    start = pd.Timestamp(year=year, month=month, day=1)
    end = start + pd.offsets.MonthEnd(0)
    dates = pd.bdate_range(start=start, end=end)
    return {value.date() for value in dates[-count:]}


def ordinary_gap_kind(current: pd.Timestamp.date, previous: pd.Timestamp.date) -> str | None:
    difference = (current - previous).days
    weekday = current.weekday()
    if weekday == 0 and difference == 3 and previous.weekday() == 4:
        return "NWOG"
    if weekday in (1, 2, 3, 4) and difference == 1:
        return "NDOG"
    return None


def ny_local_timestamp(date_value: pd.Timestamp.date, hour: int) -> pd.Timestamp:
    return pd.Timestamp(
        year=date_value.year,
        month=date_value.month,
        day=date_value.day,
        hour=hour,
        tz=NY,
    ).tz_convert("UTC")


def prior_day_levels(bars: pd.DataFrame, open_ts: pd.Timestamp) -> tuple[float, float] | None:
    previous_date = (open_ts - pd.Timedelta(days=1)).date()
    selected = bars.loc[bars.index.date == previous_date]
    if selected.empty:
        return None
    return float(selected["high"].max()), float(selected["low"].min())


def prior_week_levels(bars: pd.DataFrame, open_ts: pd.Timestamp) -> tuple[float, float] | None:
    local_date = open_ts.tz_convert(NY).date()
    current_monday = pd.Timestamp(local_date) - pd.Timedelta(days=local_date.weekday())
    start_date = (current_monday - pd.Timedelta(days=7)).date()
    end_date = (current_monday - pd.Timedelta(days=1)).date()
    dates = bars.index.date
    selected = bars.loc[(dates >= start_date) & (dates <= end_date)]
    if selected.empty:
        return None
    return float(selected["high"].max()), float(selected["low"].min())


def true_range_at(bars: pd.DataFrame, timestamp: pd.Timestamp) -> float | None:
    position = int(bars.index.searchsorted(timestamp, side="left"))
    if position < ATR_BARS + 1:
        return None
    window = bars.iloc[position - ATR_BARS:position].copy()
    previous_close = window["close"].shift(1)
    true_range = pd.concat([
        window["high"] - window["low"],
        (window["high"] - previous_close).abs(),
        (window["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    value = float(true_range.dropna().median())
    return value if math.isfinite(value) and value > 0 else None


def exact_bar(bars: pd.DataFrame, timestamp: pd.Timestamp) -> pd.Series | None:
    if timestamp not in bars.index:
        return None
    row = bars.loc[timestamp]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[-1]
    return row


def build_gap_events(
    cme_symbol: str,
    cme: pd.DataFrame,
    bars: pd.DataFrame,
) -> list[GapEvent]:
    symbol = CME_TO_EXECUTION[cme_symbol]
    events: list[GapEvent] = []
    dates = list(cme.index)
    excluded_cache: dict[tuple[int, int], set[pd.Timestamp.date]] = {}
    for previous_date, current_date in zip(dates, dates[1:]):
        kind = ordinary_gap_kind(current_date, previous_date)
        if kind is None:
            continue
        for value in (previous_date, current_date):
            key = (value.year, value.month)
            excluded_cache.setdefault(key, final_business_days(*key))
        if previous_date in excluded_cache[(previous_date.year, previous_date.month)]:
            continue
        if current_date in excluded_cache[(current_date.year, current_date.month)]:
            continue

        previous_row = cme.loc[previous_date]
        current_row = cme.loc[current_date]
        cme_prior_close = float(previous_row["close"])
        cme_open = float(current_row["open"])
        if min(cme_prior_close, cme_open) <= 0:
            continue
        open_local_date = current_date - pd.Timedelta(days=1)
        open_ts = ny_local_timestamp(open_local_date, 18)
        prior_close_ts = ny_local_timestamp(previous_date, 17)
        open_bar = exact_bar(bars, open_ts)
        close_bar = exact_bar(bars, prior_close_ts - pd.Timedelta(minutes=15))
        if open_bar is None or close_bar is None:
            continue
        execution_open = float(open_bar["open"])
        crypto_prior_close = float(close_bar["close"])
        if min(execution_open, crypto_prior_close) <= 0:
            continue
        atr = true_range_at(bars, open_ts)
        day_levels = prior_day_levels(bars, open_ts)
        week_levels = prior_week_levels(bars, open_ts)
        if atr is None or day_levels is None or week_levels is None:
            continue
        gap_return_bps = 10_000.0 * math.log(cme_open / cme_prior_close)
        halt_return_bps = 10_000.0 * math.log(execution_open / crypto_prior_close)
        mapped_prior_close = execution_open / math.exp(gap_return_bps / 10_000.0)
        gap_low, gap_high = sorted((execution_open, mapped_prior_close))
        events.append(GapEvent(
            symbol=symbol,
            cme_symbol=cme_symbol,
            trading_date=str(current_date),
            previous_trading_date=str(previous_date),
            gap_kind=kind,
            open_ts=open_ts,
            prior_close_ts=prior_close_ts,
            cme_open=cme_open,
            cme_prior_close=cme_prior_close,
            gap_return_bps=gap_return_bps,
            crypto_halt_return_bps=halt_return_bps,
            roll_residual_bps=gap_return_bps - halt_return_bps,
            execution_open=execution_open,
            mapped_prior_close=mapped_prior_close,
            gap_low=gap_low,
            gap_high=gap_high,
            gap_ce=(gap_low + gap_high) / 2.0,
            atr=atr,
            previous_day_high=day_levels[0],
            previous_day_low=day_levels[1],
            previous_week_high=week_levels[0],
            previous_week_low=week_levels[1],
        ))
    return events


def learn_thresholds(events: list[GapEvent]) -> dict[tuple[str, str, float], float]:
    thresholds: dict[tuple[str, str, float], float] = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for kind in ("NDOG", "NWOG"):
            values = np.asarray([
                abs(event.gap_return_bps)
                for event in events
                if event.symbol == symbol and event.gap_kind == kind
            ], dtype=float)
            if len(values) < 10:
                raise ValueError(f"insufficient fit gap events for {symbol} {kind}: {len(values)}")
            for quantile in (0.5, 0.75, 0.9):
                thresholds[(symbol, kind, quantile)] = float(np.quantile(values, quantile))
    return thresholds


def build_setup(
    config: Config,
    event: GapEvent,
    bars: pd.DataFrame,
    threshold: float,
) -> Setup | None:
    if config.gap_kind != "BOTH" and config.gap_kind != event.gap_kind:
        return None
    if abs(event.gap_return_bps) < threshold:
        return None
    if abs(event.roll_residual_bps) > config.max_residual_bps:
        return None
    gap_side = 1 if event.gap_return_bps > 0 else -1
    if gap_side == 0:
        return None
    start_pos = int(bars.index.searchsorted(event.open_ts, side="left"))
    end_pos = start_pos + config.confirmation_bars
    entry_pos = end_pos
    if start_pos < 0 or entry_pos >= len(bars):
        return None
    confirmation = bars.iloc[start_pos:end_pos]
    if len(confirmation) != config.confirmation_bars:
        return None
    expected_index = pd.date_range(
        start=event.open_ts,
        periods=config.confirmation_bars,
        freq="15min",
    )
    if not confirmation.index.equals(expected_index):
        return None
    entry_row = bars.iloc[entry_pos]
    entry_ts = bars.index[entry_pos]
    if entry_ts != event.open_ts + pd.Timedelta(minutes=15 * config.confirmation_bars):
        return None
    entry_price = float(entry_row["open"])
    last = confirmation.iloc[-1]
    buffer = config.stop_buffer_atr * event.atr

    if config.family == "gap_rebalance":
        side = -gap_side
        if config.trigger == "consequent_encroachment":
            trigger_price = event.gap_ce
        else:
            trigger_price = event.execution_open + 0.75 * (event.mapped_prior_close - event.execution_open)
        if side < 0:
            if float(confirmation["low"].min()) > trigger_price or float(last["close"]) > trigger_price:
                return None
            stop = max(float(confirmation["high"].max()), event.execution_open) + buffer
            target = event.mapped_prior_close
            if not (target < entry_price < stop):
                return None
        else:
            if float(confirmation["high"].max()) < trigger_price or float(last["close"]) < trigger_price:
                return None
            stop = min(float(confirmation["low"].min()), event.execution_open) - buffer
            target = event.mapped_prior_close
            if not (stop < entry_price < target):
                return None
        score = abs(event.gap_return_bps) - abs(event.roll_residual_bps)
    else:
        side = gap_side
        body = float(last["close"] - last["open"])
        if side > 0:
            if (confirmation["close"] <= event.gap_ce).any():
                return None
            if float(last["close"]) <= event.execution_open:
                return None
            if body < float(config.body_atr) * event.atr:
                return None
            stop = event.gap_ce - buffer
            target = event.previous_day_high if config.target_kind == "previous_day" else event.previous_week_high
            if not (stop < entry_price < target):
                return None
        else:
            if (confirmation["close"] >= event.gap_ce).any():
                return None
            if float(last["close"]) >= event.execution_open:
                return None
            if -body < float(config.body_atr) * event.atr:
                return None
            stop = event.gap_ce + buffer
            target = event.previous_day_low if config.target_kind == "previous_day" else event.previous_week_low
            if not (target < entry_price < stop):
                return None
        score = abs(event.gap_return_bps) + abs(body) / event.atr

    return Setup(
        config_id=config.config_id,
        family=config.family,
        symbol=event.symbol,
        gap_kind=event.gap_kind,
        trading_date=event.trading_date,
        side=side,
        event_open_ts=event.open_ts,
        confirmation_end_ts=entry_ts,
        entry_ts=entry_ts,
        entry_price=entry_price,
        stop_price=stop,
        target_price=target,
        score=score,
        gap_return_bps=event.gap_return_bps,
        roll_residual_bps=event.roll_residual_bps,
    )


def simulate_setup(
    setup: Setup,
    bars: pd.DataFrame,
    funding: pd.Series,
) -> Trade | None:
    entry_pos = int(bars.index.searchsorted(setup.entry_ts, side="left"))
    if entry_pos >= len(bars) or bars.index[entry_pos] != setup.entry_ts:
        return None
    for position in range(entry_pos, len(bars)):
        row = bars.iloc[position]
        timestamp = bars.index[position]
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        if setup.side > 0:
            if open_price <= setup.stop_price:
                exit_price, reason = open_price, "stop_gap"
            elif low <= setup.stop_price:
                exit_price, reason = setup.stop_price, "protective_stop"
            elif open_price >= setup.target_price:
                exit_price, reason = open_price, "target_gap"
            elif high >= setup.target_price:
                exit_price, reason = setup.target_price, "target"
            else:
                continue
        else:
            if open_price >= setup.stop_price:
                exit_price, reason = open_price, "stop_gap"
            elif high >= setup.stop_price:
                exit_price, reason = setup.stop_price, "protective_stop"
            elif open_price <= setup.target_price:
                exit_price, reason = open_price, "target_gap"
            elif low <= setup.target_price:
                exit_price, reason = setup.target_price, "target"
            else:
                continue
        selected_funding = funding.loc[(funding.index > setup.entry_ts) & (funding.index <= timestamp)]
        funding_bps = float((-setup.side * selected_funding).sum() * 10_000.0)
        price_bps = setup.side * math.log(exit_price / setup.entry_price) * 10_000.0
        return Trade(
            config_id=setup.config_id,
            family=setup.family,
            symbol=setup.symbol,
            gap_kind=setup.gap_kind,
            trading_date=setup.trading_date,
            side=setup.side,
            entry_ts=setup.entry_ts,
            exit_ts=timestamp,
            entry_price=setup.entry_price,
            exit_price=exit_price,
            stop_price=setup.stop_price,
            target_price=setup.target_price,
            price_bps=price_bps,
            funding_bps=funding_bps,
            gross_bps=price_bps + funding_bps,
            exit_reason=reason,
            score=setup.score,
        )
    return None


def run_candidate(
    config: Config,
    events: list[GapEvent],
    bars_by_symbol: dict[str, pd.DataFrame],
    funding_by_symbol: dict[str, pd.Series],
    thresholds: dict[tuple[str, str, float], float],
) -> tuple[list[Trade], int, int]:
    setups: list[Setup] = []
    eligible_events = 0
    for event in events:
        threshold = thresholds[(event.symbol, event.gap_kind, config.gap_quantile)]
        setup = build_setup(config, event, bars_by_symbol[event.symbol], threshold)
        if setup is not None:
            eligible_events += 1
            setups.append(setup)
    setups.sort(key=lambda item: (item.entry_ts, -item.score, item.symbol, item.family))
    trades: list[Trade] = []
    unresolved = 0
    free_time = pd.Timestamp.min.tz_localize("UTC")
    for setup in setups:
        if setup.entry_ts <= free_time:
            continue
        trade = simulate_setup(setup, bars_by_symbol[setup.symbol], funding_by_symbol[setup.symbol])
        if trade is None:
            unresolved += 1
            free_time = bars_by_symbol[setup.symbol].index.max()
            continue
        trades.append(trade)
        free_time = trade.exit_ts
    return trades, unresolved, eligible_events


def apply_cost(trades: list[Trade], cost_bps: float) -> np.ndarray:
    return np.asarray([trade.gross_bps - cost_bps for trade in trades], dtype=float)


def compounded_return(values_bps: Iterable[float]) -> float:
    values = np.asarray(list(values_bps), dtype=float) / 10_000.0
    if not len(values):
        return 0.0
    if np.any(values <= -1.0):
        return -1.0
    return float(np.prod(1.0 + values) - 1.0)


def maximum_drawdown(values_bps: Iterable[float]) -> float:
    values = np.asarray(list(values_bps), dtype=float) / 10_000.0
    nav = [1.0]
    for value in values:
        nav.append(max(0.0, nav[-1] * (1.0 + value)))
    path = np.asarray(nav, dtype=float)
    peak = np.maximum.accumulate(path)
    return float(np.max(1.0 - path / np.maximum(peak, 1e-12)))


def top_removed_return(values_bps: np.ndarray, fraction: float = 0.10) -> float:
    if not len(values_bps):
        return 0.0
    positive_indices = np.flatnonzero(values_bps > 0)
    if not len(positive_indices):
        return compounded_return(values_bps)
    count = max(1, int(math.ceil(len(values_bps) * fraction)))
    order = positive_indices[np.argsort(values_bps[positive_indices])[::-1]]
    removed = set(order[:min(count, len(order))])
    retained = [value for index, value in enumerate(values_bps) if index not in removed]
    return compounded_return(retained)


def period_labels(stage: str, trades: list[Trade]) -> dict[str, list[int]]:
    labels: dict[str, list[int]] = {}
    for index, trade in enumerate(trades):
        timestamp = trade.exit_ts
        if stage == "fit":
            label = "H1" if timestamp.month <= 6 else "H2"
        else:
            label = f"Q{(timestamp.month - 1) // 3 + 1}"
        labels.setdefault(label, []).append(index)
    required = ("H1", "H2") if stage == "fit" else ("Q1", "Q2", "Q3", "Q4")
    return {label: labels.get(label, []) for label in required}


def metrics(
    stage: str,
    trades: list[Trade],
    unresolved: int,
    eligible_events: int,
    cost_bps: float,
) -> dict[str, Any]:
    net = apply_cost(trades, cost_bps)
    positive = net[net > 0]
    negative = net[net < 0]
    total = compounded_return(net)
    days = 365
    daily = -1.0 if total <= -1.0 else float(math.expm1(math.log1p(total) / days))
    labels = period_labels(stage, trades)
    period_returns = {
        label: compounded_return(net[indices]) if indices else 0.0
        for label, indices in labels.items()
    }
    positive_sum = float(positive.sum())
    symbol_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    for trade in trades:
        symbol_counts[trade.symbol] = symbol_counts.get(trade.symbol, 0) + 1
        family_counts[trade.family] = family_counts.get(trade.family, 0) + 1
    return {
        "eligible_event_count": eligible_events,
        "trade_count": int(len(trades)),
        "unresolved_positions": int(unresolved),
        "mean_trade_bps": float(net.mean()) if len(net) else None,
        "median_trade_bps": float(np.median(net)) if len(net) else None,
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) else None,
        "total_return": total,
        "geometric_daily_growth": daily,
        "maximum_drawdown": maximum_drawdown(net),
        "top_10_percent_positive_removed_return": top_removed_return(net),
        "top_five_positive_trade_share": (
            float(np.sort(positive)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0
        ),
        "positive_period_fraction": float(sum(value > 0 for value in period_returns.values()) / len(period_returns)),
        "period_returns": period_returns,
        "symbol_counts": symbol_counts,
        "family_counts": family_counts,
        "funding_bps_total": float(sum(trade.funding_bps for trade in trades)),
    }


def gate(stage: str, metrics_by_cost: dict[str, dict[str, Any]]) -> bool:
    base = metrics_by_cost["18"]
    return (
        base["trade_count"] >= 30
        and base["unresolved_positions"] == 0
        and base["mean_trade_bps"] is not None
        and base["mean_trade_bps"] > 0
        and metrics_by_cost["12"]["median_trade_bps"] is not None
        and metrics_by_cost["12"]["median_trade_bps"] > 0
        and metrics_by_cost["24"]["total_return"] > 0
        and base["top_10_percent_positive_removed_return"] > 0
        and base["top_five_positive_trade_share"] <= 0.50
        and base["positive_period_fraction"] >= (1.0 if stage == "fit" else 0.75)
    )


def serialize_trade(trade: Trade) -> dict[str, Any]:
    value = asdict(trade)
    value["entry_ts"] = str(trade.entry_ts)
    value["exit_ts"] = str(trade.exit_ts)
    return value


def load_stage(
    session: requests.Session,
    cache: Path,
    stage: str,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.Series], list[dict[str, Any]]]:
    start, end = PERIODS[stage]
    cme_by_symbol: dict[str, pd.DataFrame] = {}
    bars_by_symbol: dict[str, pd.DataFrame] = {}
    funding_by_symbol: dict[str, pd.Series] = {}
    records: list[dict[str, Any]] = []
    for cme_symbol, execution_symbol in CME_TO_EXECUTION.items():
        cme, cme_record = load_cme_daily(session, cache, cme_symbol, start, end)
        bars, bars_record = load_klines(session, cache, execution_symbol, start, end)
        funding, funding_record = load_funding(session, cache, execution_symbol, start, end)
        cme_by_symbol[cme_symbol] = cme
        bars_by_symbol[execution_symbol] = bars
        funding_by_symbol[execution_symbol] = funding
        records.extend([cme_record, bars_record, funding_record])
        print(json.dumps({
            "stage": "source_loaded",
            "evaluation_stage": stage,
            "cme_symbol": cme_symbol,
            "execution_symbol": execution_symbol,
            "cme_rows": len(cme),
            "bar_rows": len(bars),
            "funding_rows": len(funding),
        }, sort_keys=True), flush=True)
    return cme_by_symbol, bars_by_symbol, funding_by_symbol, records


def evaluate_stage(
    stage: str,
    configs: list[Config],
    events: list[GapEvent],
    bars_by_symbol: dict[str, pd.DataFrame],
    funding_by_symbol: dict[str, pd.Series],
    thresholds: dict[tuple[str, str, float], float],
) -> tuple[list[dict[str, Any]], list[str], dict[str, list[dict[str, Any]]]]:
    rows: list[dict[str, Any]] = []
    survivors: list[str] = []
    ledgers: dict[str, list[dict[str, Any]]] = {}
    for number, config in enumerate(configs, 1):
        trades, unresolved, eligible = run_candidate(
            config, events, bars_by_symbol, funding_by_symbol, thresholds
        )
        metrics_by_cost = {
            str(cost): metrics(stage, trades, unresolved, eligible, cost)
            for cost in COSTS
        }
        passed = gate(stage, metrics_by_cost)
        if passed:
            survivors.append(config.config_id)
        rows.append({
            "config_id": config.config_id,
            "config": asdict(config),
            "stage": stage,
            "stage_pass": passed,
            "metrics": metrics_by_cost,
        })
        if trades:
            ledgers[config.config_id] = [serialize_trade(trade) for trade in trades]
        if number % 50 == 0 or number == len(configs):
            print(json.dumps({
                "stage": "candidate_progress",
                "evaluation_stage": stage,
                "done": number,
                "total": len(configs),
                "survivors_so_far": len(survivors),
            }, sort_keys=True), flush=True)
    return rows, survivors, ledgers


def best_row(rows: list[dict[str, Any]], cost: str = "18") -> dict[str, Any] | None:
    candidates = [
        row for row in rows
        if row["metrics"][cost]["trade_count"] > 0
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (
            row["metrics"][cost]["total_return"],
            row["metrics"][cost]["trade_count"],
            row["config_id"],
        ),
    )


def canonical_contract_hash(prereg: dict[str, Any]) -> str:
    payload = json.dumps(prereg, sort_keys=True, separators=(",", ":")).encode()
    return sha256(payload)


def run(cache: Path, output: Path) -> dict[str, Any]:
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    configs = config_grid()
    output.mkdir(parents=True, exist_ok=True)
    source_records: list[dict[str, Any]] = []
    stage_rows: dict[str, list[dict[str, Any]]] = {}
    stage_ledgers: dict[str, dict[str, list[dict[str, Any]]]] = {}
    stage_survivors: dict[str, list[str]] = {"fit": [], "development": [], "confirmation": []}
    opened = {"fit": False, "development": False, "confirmation": False}

    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "Mozilla/5.0 SMC-ICT-2-LIVE-CME-gap-screen/1.0",
            "Accept": "application/json,text/plain,*/*",
        })
        cme, bars, funding, records = load_stage(session, cache, "fit")
        source_records.extend(records)
        fit_events: list[GapEvent] = []
        for cme_symbol, cme_frame in cme.items():
            fit_events.extend(build_gap_events(cme_symbol, cme_frame, bars[CME_TO_EXECUTION[cme_symbol]]))
        thresholds = learn_thresholds(fit_events)
        fit_rows, fit_survivors, fit_ledgers = evaluate_stage(
            "fit", configs, fit_events, bars, funding, thresholds
        )
        opened["fit"] = True
        stage_rows["fit"] = fit_rows
        stage_ledgers["fit"] = fit_ledgers
        stage_survivors["fit"] = fit_survivors

        if fit_survivors:
            selected_configs = [config for config in configs if config.config_id in set(fit_survivors)]
            cme, bars, funding, records = load_stage(session, cache, "development")
            source_records.extend(records)
            development_events: list[GapEvent] = []
            for cme_symbol, cme_frame in cme.items():
                development_events.extend(
                    build_gap_events(cme_symbol, cme_frame, bars[CME_TO_EXECUTION[cme_symbol]])
                )
            development_rows, development_survivors, development_ledgers = evaluate_stage(
                "development", selected_configs, development_events, bars, funding, thresholds
            )
            opened["development"] = True
            stage_rows["development"] = development_rows
            stage_ledgers["development"] = development_ledgers
            stage_survivors["development"] = development_survivors

            if development_survivors:
                confirmation_configs = [
                    config for config in selected_configs
                    if config.config_id in set(development_survivors)
                ]
                cme, bars, funding, records = load_stage(session, cache, "confirmation")
                source_records.extend(records)
                confirmation_events: list[GapEvent] = []
                for cme_symbol, cme_frame in cme.items():
                    confirmation_events.extend(
                        build_gap_events(cme_symbol, cme_frame, bars[CME_TO_EXECUTION[cme_symbol]])
                    )
                confirmation_rows, confirmation_survivors, confirmation_ledgers = evaluate_stage(
                    "confirmation", confirmation_configs, confirmation_events, bars, funding, thresholds
                )
                opened["confirmation"] = True
                stage_rows["confirmation"] = confirmation_rows
                stage_ledgers["confirmation"] = confirmation_ledgers
                stage_survivors["confirmation"] = confirmation_survivors

    threshold_rows = [
        {
            "symbol": symbol,
            "gap_kind": kind,
            "quantile": quantile,
            "minimum_absolute_gap_bps": value,
        }
        for (symbol, kind, quantile), value in sorted(thresholds.items())
    ]
    write_json(output / "fit_thresholds.json", threshold_rows)
    write_json(output / "stage_candidate_results.json", stage_rows)
    write_json(output / "stage_ledgers.json", stage_ledgers)
    write_json(output / "survivors.json", stage_survivors)
    manifest = {
        "schema_version": 1,
        "claim_id": prereg["claim_id"],
        "source_records": source_records,
        "opened_stages": opened,
        "official_periods_opened": {"2024": False, "2025": False, "2026": False},
        "orders_submitted": False,
        "paper_or_testnet_started": False,
    }
    write_json(output / "source_manifest.json", manifest)

    fit_best = best_row(stage_rows["fit"])
    development_best = best_row(stage_rows.get("development", []))
    confirmation_best = best_row(stage_rows.get("confirmation", []))
    result = {
        "schema_version": 1,
        "claim_id": prereg["claim_id"],
        "result_id": prereg["provisional_result_id"],
        "screen_id": "CME-NDOG-NWOG-DELIVERY-FATAL-20260726-V1",
        "status": (
            "FATAL_SCREEN_SURVIVOR_REQUIRES_EXACT_CME_BYBIT_REPLAY"
            if stage_survivors["confirmation"]
            else "TESTED_BELOW_GATE"
        ),
        "hard_validity_status": "EXPLORATORY_CAUSAL_PASS_YAHOO_CME_BINANCE_PROXY",
        "economic_status": "SURVIVOR_REQUIRES_EXACT_REPLAY" if stage_survivors["confirmation"] else "BELOW_GATE",
        "ranking_role": "NONE",
        "qualification": "FATAL_ALPHA_SCREEN_ONLY_NOT_RANK_ELIGIBLE",
        "candidate_count": len(configs),
        "opened_stages": opened,
        "fit_survivor_count": len(stage_survivors["fit"]),
        "development_survivor_count": len(stage_survivors["development"]),
        "confirmation_survivor_count": len(stage_survivors["confirmation"]),
        "best_fit_raw": fit_best,
        "best_development_raw": development_best,
        "best_confirmation_raw": confirmation_best,
        "official_periods_opened": {"2024": False, "2025": False, "2026": False},
        "orders_submitted": False,
        "paper_or_testnet_started": False,
        "one_global_slot": True,
        "evaluation_contract_sha256": canonical_contract_hash(prereg),
        "implementation_sha256": sha256(Path(__file__).read_bytes()),
        "next_action": (
            "Freeze exact CME contract/source identities and exact Bybit BBO/depth account replay."
            if stage_survivors["confirmation"]
            else (
                "Close source after fit failure; 2022 and 2023 remained unopened."
                if not opened["development"]
                else (
                    "Close exact dependency after 2022 development failure; 2023 remained unopened."
                    if not opened["confirmation"]
                    else "Close exact dependency after 2023 confirmation failure."
                )
            )
        ),
    }
    write_json(output / "result_summary.json", result)
    inventory = {}
    for path in sorted(output.glob("*.json")):
        inventory[path.name] = {"bytes": path.stat().st_size, "sha256": sha256(path.read_bytes())}
    write_json(output / "artifact_inventory.json", inventory)
    print("CME_OPENING_GAP_RESULT=" + json.dumps({
        "fit_survivors": result["fit_survivor_count"],
        "development_survivors": result["development_survivor_count"],
        "confirmation_survivors": result["confirmation_survivor_count"],
        "opened_stages": opened,
        "best_fit": None if fit_best is None else fit_best["config_id"],
    }, sort_keys=True), flush=True)
    return result


def synthetic_bars(start: str, periods: int, base: float = 100.0) -> pd.DataFrame:
    index = pd.date_range(start=start, periods=periods, freq="15min", tz="UTC")
    drift = np.linspace(0.0, 5.0, periods)
    close = base + drift + np.sin(np.arange(periods) / 20.0)
    open_values = np.r_[close[0], close[:-1]]
    high = np.maximum(open_values, close) + 0.3
    low = np.minimum(open_values, close) - 0.3
    return pd.DataFrame({
        "open": open_values,
        "high": high,
        "low": low,
        "close": close,
        "volume": 10.0,
        "turnover": close * 10.0,
    }, index=index)


def self_test() -> None:
    configs = config_grid()
    assert len(configs) == 432
    bars = synthetic_bars("2021-01-01", 365 * 96)
    cme_dates = pd.bdate_range("2021-01-04", "2021-12-31").date
    cme = pd.DataFrame(index=cme_dates)
    cme["open"] = np.linspace(100.0, 120.0, len(cme))
    cme["close"] = cme["open"] * (1.0 + 0.001 * np.sin(np.arange(len(cme)) / 5.0))
    cme["high"] = np.maximum(cme["open"], cme["close"]) * 1.01
    cme["low"] = np.minimum(cme["open"], cme["close"]) * 0.99
    cme["volume"] = 100.0
    events = build_gap_events("BTC=F", cme, bars)
    assert events
    duplicated = [
        GapEvent(**{**asdict(event), "symbol": "ETHUSDT", "cme_symbol": "ETH=F"})
        for event in events
    ]
    thresholds = learn_thresholds(events + duplicated)
    for key, value in thresholds.items():
        assert key[0] in {"BTCUSDT", "ETHUSDT"} and value >= 0

    event = events[len(events) // 2]
    position = bars.index.searchsorted(event.open_ts)
    changed = bars.copy()
    if event.gap_return_bps > 0:
        changed.iloc[position:position + 2, changed.columns.get_loc("close")] = event.gap_ce * 0.999
        changed.iloc[position:position + 2, changed.columns.get_loc("low")] = event.gap_ce * 0.998
    else:
        changed.iloc[position:position + 2, changed.columns.get_loc("close")] = event.gap_ce * 1.001
        changed.iloc[position:position + 2, changed.columns.get_loc("high")] = event.gap_ce * 1.002
    config = next(config for config in configs if config.family == "gap_rebalance" and config.confirmation_bars == 1)
    setup = build_setup(config, event, changed, 0.0)
    if setup is not None:
        assert setup.entry_ts > setup.event_open_ts
        assert (setup.side > 0 and setup.stop_price < setup.entry_price < setup.target_price) or (
            setup.side < 0 and setup.target_price < setup.entry_price < setup.stop_price
        )
    net = np.asarray([10.0, -5.0, 20.0])
    assert compounded_return(net) > 0
    assert maximum_drawdown(net) >= 0
    print("SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        run(args.cache, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
