"""Execute the sealed economic route with pinned immutable Bybit mirrors only."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from . import run as sealed_run
from .common import CachedDownloader, MarketData
from .source_hf_pinned_v2 import load_markets_hf_pinned_listing_aware

_MARKETS: dict[str, MarketData] = {}


def prepare_sources(
    downloader: CachedDownloader,
    symbols: Sequence[str],
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> dict[str, list[Path]]:
    # The sealed runner passes the contract only into load_market, so defer the
    # actual pinned load until the first symbol call while preserving its source
    # loop shape.
    return {str(symbol): [] for symbol in symbols}


def load_market_pinned(
    symbol: str,
    _paths: Sequence[Path],
    downloader: CachedDownloader,
    contract: Mapping[str, Any],
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> MarketData:
    if not _MARKETS:
        _MARKETS.update(
            load_markets_hf_pinned_listing_aware(
                downloader,
                list(contract["symbols"]),
                start,
                end_exclusive,
                contract,
            )
        )
    return _MARKETS[symbol]


sealed_run.download_bybit_months = prepare_sources
sealed_run.load_market = load_market_pinned


def main() -> int:
    return sealed_run.main()


if __name__ == "__main__":
    raise SystemExit(main())
