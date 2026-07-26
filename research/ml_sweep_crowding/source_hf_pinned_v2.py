"""Symbol-listing-aware wrapper for immutable Bybit price/funding mirrors."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .common import CachedDownloader, MarketData, SourceGateError
from .source_data import (
    build_five_minute_features,
    construct_funding_cumulative,
    load_binance_metrics,
)
from .source_hf_pinned import (
    _download_pinned,
    load_pinned_funding,
    load_pinned_one_minute,
)


def load_markets_hf_pinned_listing_aware(
    downloader: CachedDownloader,
    symbols: Sequence[str],
    global_start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    contract: Mapping[str, Any],
) -> dict[str, MarketData]:
    price = contract["data"]["pinned_bybit_one_minute_mirror"]
    funding = contract["data"]["pinned_bybit_funding_mirror"]
    if str(price["revision"]) != str(funding["revision"]):
        raise SourceGateError("price and funding mirror revisions differ")
    listing_starts = contract["data"]["bybit_symbol_first_expected"]
    markets: dict[str, MarketData] = {}
    for symbol in symbols:
        symbol_start = max(
            global_start,
            pd.Timestamp(str(listing_starts[symbol])).tz_convert("UTC")
            if pd.Timestamp(str(listing_starts[symbol])).tzinfo is not None
            else pd.Timestamp(str(listing_starts[symbol]), tz="UTC"),
        )
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
        metrics, metrics_hash = load_binance_metrics(
            downloader,
            symbol,
            symbol_start,
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
