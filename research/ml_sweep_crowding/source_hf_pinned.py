"""Pinned Bybit-derived one-minute price and actual funding transport.

The immutable revision, file paths and SHA-256 values are supplied by the
pre-outcome contract after the dedicated coverage probe passes.  No scientific
or account rule lives in this module.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote

import numpy as np
import pandas as pd

from .common import CachedDownloader, MarketData, SourceGateError, sha256_file, sha256_json
from .source_data import (
    build_five_minute_features,
    construct_funding_cumulative,
    load_binance_metrics,
)


def _download_pinned(
    downloader: CachedDownloader,
    dataset_id: str,
    revision: str,
    repository_path: str,
    expected_sha256: str,
    cache_group: str,
) -> Path:
    encoded = quote(repository_path, safe="/")
    url = (
        f"https://huggingface.co/datasets/{dataset_id}/resolve/"
        f"{revision}/{encoded}?download=true"
    )
    local = downloader.get(
        url,
        f"{cache_group}/{revision}/{Path(repository_path).name}",
        1024,
    )
    observed = sha256_file(local)
    if observed != expected_sha256:
        raise SourceGateError(
            f"pinned file hash mismatch for {repository_path}: {observed} != {expected_sha256}"
        )
    return local


def _timestamp(raw: pd.Series) -> pd.DatetimeIndex:
    if pd.api.types.is_numeric_dtype(raw):
        numeric = pd.to_numeric(raw, errors="coerce")
        median = float(numeric.dropna().median()) if numeric.notna().any() else math.nan
        if median > 1e15:
            unit = "ns"
        elif median > 1e11:
            unit = "ms"
        else:
            unit = "s"
        return pd.DatetimeIndex(pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce"))
    return pd.DatetimeIndex(pd.to_datetime(raw, utc=True, errors="coerce"))


def load_pinned_one_minute(
    path: Path,
    symbol: str,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    minimum_coverage: float,
) -> tuple[pd.DataFrame, float, str]:
    frame = pd.read_parquet(path)
    columns = {str(column).lower(): str(column) for column in frame.columns}
    time_name = next(
        (
            columns[name]
            for name in ("date", "timestamp", "time", "datetime", "start_time")
            if name in columns
        ),
        None,
    )
    required = ["open", "high", "low", "close", "volume"]
    missing = [name for name in required if name not in columns]
    if time_name is None or missing:
        raise SourceGateError(
            f"{symbol} pinned 1m schema unsupported: time={time_name}, missing={missing}, "
            f"columns={list(frame.columns)}"
        )
    normalized = pd.DataFrame(index=_timestamp(frame[time_name]))
    normalized.index.name = "timestamp"
    for name in required:
        normalized[name] = pd.to_numeric(frame[columns[name]], errors="coerce").to_numpy()
    normalized = normalized.loc[
        (normalized.index >= start) & (normalized.index < end_exclusive)
    ]
    normalized = normalized[~normalized.index.duplicated(keep="last")].sort_index()
    if normalized.empty:
        raise SourceGateError(f"{symbol} pinned 1m interval empty")
    expected = pd.date_range(start, end_exclusive, freq="1min", inclusive="left")
    observed = int(normalized.index.nunique())
    coverage = observed / max(len(expected), 1)
    if coverage < minimum_coverage:
        raise SourceGateError(
            f"{symbol} pinned 1m coverage {coverage:.6%} below {minimum_coverage:.6%}"
        )
    if normalized.index.min() > start + pd.Timedelta(minutes=2):
        raise SourceGateError(f"{symbol} pinned 1m starts late: {normalized.index.min()}")
    if normalized.index.max() < end_exclusive - pd.Timedelta(minutes=2):
        raise SourceGateError(f"{symbol} pinned 1m ends early: {normalized.index.max()}")
    normalized = normalized.reindex(expected)
    o = normalized["open"]
    h = normalized["high"]
    l = normalized["low"]
    c = normalized["close"]
    impossible = (
        (h < pd.concat([o, l, c], axis=1).max(axis=1))
        | (l > pd.concat([o, h, c], axis=1).min(axis=1))
        | (pd.concat([o, h, l, c], axis=1) <= 0).any(axis=1)
    )
    if bool(impossible.fillna(False).any()):
        raise SourceGateError(f"{symbol} pinned 1m contains impossible OHLC")
    fingerprint = sha256_json(
        {
            "symbol": symbol,
            "file_sha256": sha256_file(path),
            "start": start.isoformat(),
            "end_exclusive": end_exclusive.isoformat(),
            "coverage": coverage,
            "observed_rows": observed,
        }
    )
    return normalized, coverage, fingerprint


def normalize_funding_open(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {str(column).lower(): str(column) for column in frame.columns}
    time_name = next(
        (
            columns[name]
            for name in ("date", "timestamp", "time", "datetime", "funding_time")
            if name in columns
        ),
        None,
    )
    if time_name is None or "open" not in columns:
        raise SourceGateError(f"pinned funding schema unsupported: {list(frame.columns)}")
    timestamp = _timestamp(frame[time_name])
    rate = pd.to_numeric(frame[columns["open"]], errors="coerce")
    result = pd.DataFrame(
        {"funding_rate": rate.to_numpy(dtype=float)}, index=timestamp
    )
    result.index.name = "timestamp"
    result = result.dropna().loc[~result.index.duplicated(keep="last")].sort_index()
    if result["funding_rate"].nunique() < 10:
        raise SourceGateError("pinned funding rate column is degenerate")
    return result


def load_pinned_funding(
    path: Path,
    symbol: str,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> tuple[pd.DataFrame, str]:
    frame = normalize_funding_open(pd.read_parquet(path))
    frame = frame.loc[(frame.index >= start) & (frame.index < end_exclusive)]
    if frame.empty:
        raise SourceGateError(f"{symbol} pinned funding interval empty")
    gaps = frame.index.to_series().diff().dropna()
    median_gap = gaps.median() if len(gaps) else pd.Timedelta(0)
    max_gap = gaps.max() if len(gaps) else pd.Timedelta(0)
    if not (pd.Timedelta(hours=4) <= median_gap <= pd.Timedelta(hours=12, minutes=1)):
        raise SourceGateError(f"{symbol} funding cadence invalid: median {median_gap}")
    if max_gap > pd.Timedelta(hours=24, minutes=1):
        raise SourceGateError(f"{symbol} funding gap exceeds 24h: {max_gap}")
    if frame.index.min() > start + pd.Timedelta(hours=16):
        raise SourceGateError(f"{symbol} pinned funding starts late: {frame.index.min()}")
    if frame.index.max() < end_exclusive - pd.Timedelta(hours=16):
        raise SourceGateError(f"{symbol} pinned funding ends early: {frame.index.max()}")
    rates = frame["funding_rate"].to_numpy(dtype=float)
    if not np.isfinite(rates).all() or float(np.max(np.abs(rates))) > 0.10:
        raise SourceGateError(f"{symbol} funding finite/range gate failed")
    return frame, sha256_file(path)


def load_markets_hf_pinned(
    downloader: CachedDownloader,
    symbols: Sequence[str],
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    contract: Mapping[str, Any],
) -> dict[str, MarketData]:
    price = contract["data"]["pinned_bybit_one_minute_mirror"]
    funding = contract["data"]["pinned_bybit_funding_mirror"]
    if str(price["revision"]) != str(funding["revision"]):
        raise SourceGateError("price and funding mirror revisions differ")
    markets: dict[str, MarketData] = {}
    for symbol in symbols:
        price_path = _download_pinned(
            downloader,
            str(price["dataset_id"]),
            str(price["revision"]),
            str(price["files"][symbol]),
            str(price["sha256"][symbol]),
            "hf_bybit_price",
        )
        funding_path = _download_pinned(
            downloader,
            str(funding["dataset_id"]),
            str(funding["revision"]),
            str(funding["files"][symbol]),
            str(funding["sha256"][symbol]),
            "hf_bybit_funding",
        )
        one, coverage, one_hash = load_pinned_one_minute(
            price_path,
            symbol,
            start,
            end_exclusive,
            float(contract["data"]["minimum_one_minute_coverage"]),
        )
        funding_frame, funding_hash = load_pinned_funding(
            funding_path, symbol, start, end_exclusive
        )
        metrics, metrics_hash = load_binance_metrics(
            downloader,
            symbol,
            start,
            end_exclusive,
            contract["data"]["binance_metrics_mirror_pattern"],
        )
        five = build_five_minute_features(symbol, one, metrics, contract)
        funding_cum = construct_funding_cumulative(one, funding_frame)
        markets[symbol] = MarketData(
            symbol=symbol,
            one_minute=one,
            five_minute=five,
            funding=funding_frame,
            funding_long_cum=funding_cum,
            minute_open=one["open"].to_numpy(dtype=np.float64, copy=True),
            minute_high=one["high"].to_numpy(dtype=np.float64, copy=True),
            minute_low=one["low"].to_numpy(dtype=np.float64, copy=True),
            minute_close=one["close"].to_numpy(dtype=np.float64, copy=True),
            coverage=coverage,
            one_minute_sha256=one_hash,
            metrics_sha256=metrics_hash,
            funding_sha256=funding_hash,
        )
    return markets
