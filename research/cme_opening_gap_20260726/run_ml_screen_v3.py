from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import run_ml_screen as base
import run_ml_screen_v2 as purged

_ORIGINAL_LOAD_STAGE = base.core.load_stage
_PATCHED = False


def load_stage_with_turnover_alias(*args, **kwargs):
    cme_by_symbol, bars_by_symbol, funding_by_symbol, records = _ORIGINAL_LOAD_STAGE(
        *args, **kwargs
    )
    for symbol, frame in bars_by_symbol.items():
        if "quote_volume" not in frame.columns:
            if "turnover" not in frame.columns:
                raise KeyError(f"{symbol} has neither quote_volume nor turnover")
            frame["quote_volume"] = frame["turnover"]
        if not frame["quote_volume"].equals(frame["turnover"]):
            raise AssertionError(f"{symbol} turnover alias changed values")
    return cme_by_symbol, bars_by_symbol, funding_by_symbol, records


def patch_loader() -> None:
    global _PATCHED
    if _PATCHED:
        return
    base.core.load_stage = load_stage_with_turnover_alias
    _PATCHED = True


def run(output: Path, cache: Path) -> dict[str, Any]:
    patch_loader()
    return purged.run(output, cache)


def self_test() -> None:
    purged.self_test()
    import pandas as pd

    index = pd.date_range("2021-01-01T00:00:00Z", periods=3, freq="15min")
    frame = pd.DataFrame({
        "open": [1.0, 1.0, 1.0],
        "high": [1.1, 1.1, 1.1],
        "low": [0.9, 0.9, 0.9],
        "close": [1.0, 1.0, 1.0],
        "volume": [1.0, 1.0, 1.0],
        "turnover": [10.0, 20.0, 30.0],
    }, index=index)

    def fake_loader(*args, **kwargs):
        return {}, {"BTCUSDT": frame.copy()}, {}, []

    global _ORIGINAL_LOAD_STAGE
    original = _ORIGINAL_LOAD_STAGE
    try:
        _ORIGINAL_LOAD_STAGE = fake_loader
        _, bars, _, _ = load_stage_with_turnover_alias(None, None, None)
        assert "quote_volume" in bars["BTCUSDT"].columns
        assert bars["BTCUSDT"]["quote_volume"].equals(bars["BTCUSDT"]["turnover"])
    finally:
        _ORIGINAL_LOAD_STAGE = original
    print("TURNOVER_ALIAS_SELF_TEST_PASS")


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
