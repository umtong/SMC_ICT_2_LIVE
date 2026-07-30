"""Listing-aware immutable Bybit prices/funding and Binance positioning metrics."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .common import CachedDownloader, MarketData, SourceGateError, sha256_file
from .source_data import (
    build_five_minute_features,
    construct_funding_cumulative,
    parse_metric_timestamp,
)
from .source_hf_pinned import (
    _download_pinned,
    load_pinned_funding,
    load_pinned_one_minute,
)

METRIC_COLUMNS = [
    "create_time",
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
]


def _utc(value: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def load_pinned_binance_metrics(
    downloader: CachedDownloader,
    symbol: str,
    price_start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, str, pd.Timestamp]:
    spec = contract["data"]["pinned_binance_metrics_mirror"]
    local = _download_pinned(
        downloader,
        str(spec["dataset_id"]),
        str(spec["revision"]),
        str(spec["files"][symbol]),
        str(spec["sha256"][symbol]),
        "binance_metrics_pinned",
    )
    frame = pd.read_parquet(local, columns=METRIC_COLUMNS)
    frame.index = parse_metric_timestamp(frame.pop("create_time"))
    frame = frame[~frame.index.isna()].sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    metric_start = max(price_start, _utc(str(spec["first_expected"][symbol])))
    frame = frame.loc[
        (frame.index >= metric_start - pd.Timedelta(days=2))
        & (frame.index < end_exclusive)
    ]
    if frame.empty:
        raise SourceGateError(f"{symbol} pinned Binance metrics are empty")
    expected = len(pd.date_range(metric_start, end_exclusive, freq="5min", inclusive="left"))
    observed = int(frame.loc[frame.index >= metric_start].index.floor("5min").nunique())
    coverage = observed / max(expected, 1)
    minimum = float(spec["minimum_clock_coverage_from_first_expected"])
    if coverage < minimum:
        raise SourceGateError(
            f"{symbol} pinned Binance metric coverage {coverage:.6%} below {minimum:.6%} "
            f"from actual source start {metric_start.isoformat()}"
        )
    if frame.index.min() > metric_start + pd.Timedelta(minutes=10):
        raise SourceGateError(f"{symbol} pinned Binance metrics start late: {frame.index.min()}")
    if frame.index.max() < end_exclusive - pd.Timedelta(minutes=10):
        raise SourceGateError(f"{symbol} pinned Binance metrics end early: {frame.index.max()}")
    required_positive = [
        "sum_open_interest_value",
        "count_long_short_ratio",
        "sum_taker_long_short_vol_ratio",
    ]
    for column in required_positive:
        series = frame.loc[frame.index >= metric_start, column]
        if float(series.notna().mean()) < 0.70 or int(series.nunique(dropna=True)) < 100:
            raise SourceGateError(f"{symbol} pinned Binance metric {column} is degenerate")
    return frame, sha256_file(local), metric_start


def load_markets_hf_pinned_v3(
    downloader: CachedDownloader,
    symbols: Sequence[str],
    global_start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    contract: Mapping[str, Any],
) -> dict[str, MarketData]:
    price = contract["data"]["pinned_bybit_one_minute_mirror"]
    funding = contract["data"]["pinned_bybit_funding_mirror"]
    metrics = contract["data"]["pinned_binance_metrics_mirror"]
    revisions = {str(price["revision"]), str(funding["revision"])}
    if len(revisions) != 1:
        raise SourceGateError("Bybit price and funding mirror revisions differ")
    listing_starts = contract["data"]["bybit_symbol_first_expected"]
    markets: dict[str, MarketData] = {}
    for symbol in symbols:
        symbol_start = max(global_start, _utc(str(listing_starts[symbol])))
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
            symbol_start,
            end_exclusive,
            float(contract["data"]["minimum_one_minute_coverage"]),
        )
        funding_frame, funding_hash = load_pinned_funding(
            funding_path, symbol, symbol_start, end_exclusive
        )
        metric_frame, metric_hash, _metric_start = load_pinned_binance_metrics(
            downloader, symbol, symbol_start, end_exclusive, contract
        )
        five = build_five_minute_features(symbol, one, metric_frame, contract)
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
            metrics_sha256=metric_hash,
            funding_sha256=funding_hash,
        )
    return markets
