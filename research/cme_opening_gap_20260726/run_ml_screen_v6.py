from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

import run_ml_screen_v5 as v5

_ORIGINAL_LOAD_STAGE = v5.ORIGINAL_LOAD_STAGE
_PATCHED = False


def load_stage_with_utc_funding_index(*args, **kwargs):
    cme_by_symbol, bars_by_symbol, funding_by_symbol, records = _ORIGINAL_LOAD_STAGE(
        *args, **kwargs
    )
    normalized: dict[str, pd.Series] = {}
    for symbol, series in funding_by_symbol.items():
        values = series.copy()
        original_rates = values.to_numpy(copy=True)
        index = pd.DatetimeIndex(
            pd.to_datetime(values.index, utc=True, errors="raise", format="mixed")
        )
        if index.has_duplicates:
            raise ValueError(f"duplicate cached funding timestamps for {symbol}")
        values.index = index
        values = values.sort_index()
        if len(values) != len(original_rates):
            raise AssertionError(f"funding row count changed for {symbol}")
        if not (values.to_numpy() == original_rates).all():
            raise AssertionError(f"funding rate values changed for {symbol}")
        normalized[symbol] = values
    return cme_by_symbol, bars_by_symbol, normalized, records


def patch_cache_loader() -> None:
    global _PATCHED
    if _PATCHED:
        return
    v5.ORIGINAL_LOAD_STAGE = load_stage_with_utc_funding_index
    _PATCHED = True


def run(output: Path, cache: Path) -> dict[str, Any]:
    patch_cache_loader()
    return v5.run(output, cache)


def self_test() -> None:
    v5.self_test()
    index = [
        "2021-01-01 00:00:00.000000+00:00",
        "2021-01-02 00:00:00+00:00",
        "2021-01-02T08:00:00Z",
    ]
    rates = pd.Series([0.0001, -0.0002, 0.0003], index=index, name="rate")

    def fake_loader(*args, **kwargs):
        return {}, {}, {"BTCUSDT": rates.copy()}, []

    global _ORIGINAL_LOAD_STAGE
    original = _ORIGINAL_LOAD_STAGE
    try:
        _ORIGINAL_LOAD_STAGE = fake_loader
        _, _, funding, _ = load_stage_with_utc_funding_index(None, None, None)
        result = funding["BTCUSDT"]
        assert isinstance(result.index, pd.DatetimeIndex)
        assert str(result.index.tz) == "UTC"
        assert result.index.is_monotonic_increasing
        assert result.tolist() == rates.tolist()
    finally:
        _ORIGINAL_LOAD_STAGE = original
    print("CACHE_FUNDING_TIMESTAMP_SELF_TEST_PASS")


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
        run(args.output, args.cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
