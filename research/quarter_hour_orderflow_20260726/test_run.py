from __future__ import annotations

import math
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

import run
import source


def test_timestamp_normalization_numeric_and_iso() -> None:
    expected = 1_640_995_200_000
    assert source.normalize_timestamp_ms("1640995200000") == expected
    assert source.normalize_timestamp_ms("1640995200000000") == expected
    assert source.normalize_timestamp_ms("2022-01-01 00:00:00") == expected


def test_agg_window_sign_and_extremes(tmp_path: Path) -> None:
    path = tmp_path / "agg.zip"
    start = source.utc_day_start_ms("2022-01-01")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "agg.csv",
            "1,100,2,1,1,%d,false\n2,99,1,2,2,%d,true\n" % (start + 1_000, start + 2_000),
        )
    frame = source.load_agg_windows(path, "2022-01-01")
    first = frame[(frame.phase == "quarter") & (frame.event_start_ms == start)].iloc[0]
    assert bool(first.valid)
    assert first.high_price == 100
    assert first.low_price == 99
    assert first.trade_count == 2
    expected = (200.0 - 99.0) / (200.0 + 99.0)
    assert math.isclose(first.imbalance, expected)


def _bars() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    index = pd.Index([0, 60_000, 120_000], name="open_ms")
    contract = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0],
            "high": [101.0, 103.0, 104.0],
            "low": [99.0, 98.0, 99.0],
            "close": [100.0, 101.0, 103.0],
            "quote_volume": [1_000_000.0] * 3,
            "taker_buy_quote": [500_000.0] * 3,
            "valid": [True] * 3,
        },
        index=index,
    )
    mark = contract[["open", "high", "low", "close", "valid"]].copy()
    funding = pd.DataFrame({"funding_rate": []}, index=pd.Index([], dtype=np.int64))
    return contract, mark, funding


def test_same_bar_target_stop_is_adverse() -> None:
    contract, mark, funding = _bars()
    outcome = run.resolve_path(
        contract,
        mark,
        funding,
        entry_ms=0,
        side=1,
        entry_price=100.0,
        stop_price=99.0,
        target_price=101.0,
    )
    assert outcome.status == "stop"
    assert outcome.exit_price == 99.0


def test_no_elapsed_exit_produces_unresolved() -> None:
    contract, mark, funding = _bars()
    outcome = run.resolve_path(
        contract,
        mark,
        funding,
        entry_ms=0,
        side=1,
        entry_price=100.0,
        stop_price=90.0,
        target_price=110.0,
    )
    assert outcome.status == "unresolved"
    assert outcome.exit_ms is None
    assert outcome.gross_return is None


def test_structural_target_stop_orientation() -> None:
    target, stop = run._target_stop(
        side=1,
        mode="continuation",
        entry_price=100.0,
        event_high=100.5,
        event_low=99.5,
        prior_15m_high=101.0,
        prior_15m_low=98.0,
        prior_240m_high=105.0,
        prior_240m_low=95.0,
        atr_15m_abs=1.0,
    )
    assert stop < 100 < target
