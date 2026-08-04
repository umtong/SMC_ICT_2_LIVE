from __future__ import annotations

import math

import pandas as pd
import pytest

from scripts.lrds.canonical_adapter import (
    CanonicalDataContractError,
    CanonicalDecisionStream,
    first_exact_execution,
)


def test_canonical_stream_never_emits_future_missing_or_incomplete_rows() -> None:
    frame = pd.DataFrame({
        "start_time_ms": [0, 60_000, 120_000, 180_000, 240_000],
        "available_at_ms": [60_000, 120_000, 180_000, 240_000, 300_000],
        "observed": [True, False, True, True, True],
        "is_complete": [True, True, False, True, True],
        "open": [100.0, math.nan, 102.0, 103.0, 104.0],
        "high": [101.0, math.nan, 103.0, 104.0, 105.0],
        "low": [99.0, math.nan, 101.0, 102.0, 103.0],
        "close": [100.5, math.nan, 102.5, 103.5, 104.5],
    })
    bars, audit = CanonicalDecisionStream(frame).visible(240_000)
    assert [bar.index for bar in bars] == [0, 3]
    assert [bar.available_at_ms for bar in bars] == [60_000, 240_000]
    assert audit.total_rows == 5
    assert audit.emitted_rows == 2
    assert audit.future_rows == 1
    assert audit.missing_rows == 1
    assert audit.incomplete_rows == 1


def test_cursor_emits_each_completed_bar_once_and_rejects_time_reversal() -> None:
    frame = pd.DataFrame({
        "start_time_ms": [0, 60_000, 120_000],
        "available_at_ms": [60_000, 120_000, 180_000],
        "observed": [True, False, True],
        "open": [100.0, math.nan, 102.0],
        "high": [101.0, math.nan, 103.0],
        "low": [99.0, math.nan, 101.0],
        "close": [100.5, math.nan, 102.5],
    })
    cursor = CanonicalDecisionStream(frame).cursor()
    assert [bar.index for bar in cursor.advance(60_000)] == [0]
    assert cursor.advance(60_000) == ()
    assert cursor.advance(120_000) == ()
    assert [bar.index for bar in cursor.advance(180_000)] == [2]
    with pytest.raises(CanonicalDataContractError, match="move backward"):
        cursor.advance(179_999)


def test_duplicate_grid_starts_fail_closed() -> None:
    frame = pd.DataFrame({
        "start_time_ms": [0, 0],
        "available_at_ms": [60_000, 60_000],
        "open": [1.0, 1.0], "high": [2.0, 2.0],
        "low": [0.5, 0.5], "close": [1.5, 1.5],
    })
    with pytest.raises(CanonicalDataContractError, match="duplicate starts"):
        CanonicalDecisionStream(frame)


def _half_second_frame() -> pd.DataFrame:
    values = {"start_time_ms": [1_000], "source_available": [True]}
    for half in ("h0", "h1"):
        observed = half == "h1"
        values[f"{half}_observed"] = [observed]
        values[f"{half}_available_at_ms"] = [2_000 if half == "h0" else 2_500]
        for column in (
            "open", "high", "low", "close", "volume", "turnover",
            "trade_count", "buy_volume", "sell_volume", "buy_turnover",
            "sell_turnover",
        ):
            value = 0.0
            if column in {"open", "high", "low", "close"}:
                value = 101.25
            elif column == "trade_count":
                value = 1
            elif column in {"volume", "turnover", "buy_volume", "buy_turnover"}:
                value = 1.0
            values[f"{half}_{column}"] = [value]
        values[f"{half}_first_offset_ms"] = [-1 if not observed else 25]
        values[f"{half}_high_offset_ms"] = [-1 if not observed else 25]
        values[f"{half}_low_offset_ms"] = [-1 if not observed else 25]
        values[f"{half}_last_offset_ms"] = [-1 if not observed else 25]
    return pd.DataFrame(values)


def test_exact_execution_uses_first_observed_trade_after_aligned_500ms() -> None:
    execution = first_exact_execution(_half_second_frame(), 1_000)
    assert execution is not None
    assert execution.activation_time_ms == 1_500
    assert execution.half_start_time_ms == 1_500
    assert execution.trade_time_ms == 1_525
    assert execution.price == pytest.approx(101.25)
    assert execution.side_is_unambiguous_buy


def test_exact_execution_rejects_unaligned_decision_clock() -> None:
    with pytest.raises(ValueError, match="aligned"):
        first_exact_execution(_half_second_frame(), 1_250)
