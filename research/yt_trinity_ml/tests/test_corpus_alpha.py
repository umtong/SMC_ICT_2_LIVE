from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from system.core import EventFamily  # noqa: E402
from system.corpus_alpha import build_corpus_features, generate_corpus_candidates  # noqa: E402


def _raw_bars(count: int = 500) -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=count, freq="5min", tz="UTC")
    rng = np.random.default_rng(73)
    returns = rng.normal(0, 0.0014, count)
    close = 20000 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.maximum(close * rng.uniform(0.0003, 0.0018, count), 1.0)
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.lognormal(5, 0.5, count)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def _features(rows: list[dict[str, float]]) -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=len(rows), freq="5min", tz="UTC")
    defaults: dict[str, float] = {
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "atr": 1.0,
        "body_atr": 0.0,
        "close_location": 0.5,
        "bull_bos": 0.0,
        "bear_bos": 0.0,
        "internal_high_3": 102.0,
        "internal_low_3": 98.0,
        "last_swing_high": 105.0,
        "last_swing_low": 95.0,
        "previous_day_high": 105.0,
        "previous_day_low": 90.0,
        "previous_week_high": 120.0,
        "previous_week_low": 80.0,
        "previous_1h_high": 104.0,
        "previous_1h_low": 96.0,
        "previous_4h_high": 110.0,
        "previous_4h_low": 92.0,
        "trend_alignment_score": 0.0,
        "volume_z": 0.0,
        "bull_fvg_lower": np.nan,
        "bull_fvg_upper": np.nan,
        "bear_fvg_lower": np.nan,
        "bear_fvg_upper": np.nan,
        "last_bearish_body_low": 99.0,
        "last_bearish_body_high": 100.0,
        "last_bullish_body_low": 100.0,
        "last_bullish_body_high": 101.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows], index=index)


def test_corpus_features_do_not_change_when_future_is_appended() -> None:
    frame = _raw_bars()
    short = build_corpus_features(frame.iloc[:400])
    long = build_corpus_features(frame)
    pd.testing.assert_frame_equal(short, long.loc[short.index], check_dtype=False)


def test_reversal_requires_later_confirmation_and_first_retest() -> None:
    frame = _features(
        [
            {"high": 103, "low": 99, "close": 101},
            {"high": 104, "low": 100, "close": 103},
            {"high": 104, "low": 101, "close": 103},
            {"open": 104, "high": 106, "low": 102, "close": 104, "internal_low_3": 100},
            {
                "open": 104,
                "high": 104.2,
                "low": 98,
                "close": 99,
                "body_atr": -1.0,
                "close_location": 0.1,
                "bear_fvg_lower": 102,
                "bear_fvg_upper": 103,
            },
            {"open": 102.4, "high": 102.8, "low": 101.5, "close": 101.8, "body_atr": -0.6, "close_location": 0.2},
            {"open": 101, "high": 102.5, "low": 94, "close": 95},
        ]
    )
    events = generate_corpus_candidates(frame, "BTCUSDT")
    assert len(events) == 1
    event = events[0]
    assert event.timestamp == frame.index[5]
    assert event.family == EventFamily.LIQUIDITY_SWEEP_REVERSAL and event.side == -1
    assert event.stop_reference > 106
    assert event.target_reference == 96
    assert event.feature_row["swept_level_count"] >= 1
    assert not any(item.timestamp in {frame.index[3], frame.index[4]} for item in events)


def test_continuation_waits_for_first_fvg_retest() -> None:
    frame = _features(
        [
            {"high": 101, "low": 98, "close": 100},
            {"high": 102, "low": 99, "close": 101},
            {
                "open": 101,
                "high": 105,
                "low": 101,
                "close": 104,
                "body_atr": 1.0,
                "close_location": 0.9,
                "bull_bos": 1.0,
                "bull_fvg_lower": 100,
                "bull_fvg_upper": 101,
                "trend_alignment_score": 3,
                "last_swing_low": 98,
                "last_swing_high": 103,
                "previous_day_high": 110,
                "previous_1h_high": 108,
            },
            {
                "open": 100.7,
                "high": 102,
                "low": 100.4,
                "close": 101.5,
                "body_atr": 0.8,
                "close_location": 0.8,
                "trend_alignment_score": 3,
                "last_swing_low": 98,
                "last_swing_high": 103,
                "previous_day_high": 110,
                "previous_1h_high": 108,
            },
        ]
    )
    events = generate_corpus_candidates(frame, "ETHUSDT")
    assert len(events) == 1
    event = events[0]
    assert event.timestamp == frame.index[3]
    assert event.family == EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION and event.side == 1
    assert event.stop_reference < event.entry_reference < event.target_reference
    assert event.target_reference == 108
    assert not any(item.timestamp == frame.index[2] for item in events)


def test_first_touch_without_rejection_consumes_setup() -> None:
    frame = _features(
        [
            {"high": 103, "low": 99, "close": 101},
            {"high": 104, "low": 100, "close": 103},
            {"high": 104, "low": 101, "close": 103},
            {"open": 104, "high": 106, "low": 102, "close": 104, "internal_low_3": 100},
            {
                "open": 104,
                "high": 104.2,
                "low": 98,
                "close": 99,
                "body_atr": -1.0,
                "close_location": 0.1,
                "bear_fvg_lower": 102,
                "bear_fvg_upper": 103,
            },
            {"open": 101.5, "high": 102.5, "low": 101.2, "close": 102.4, "body_atr": 0.9, "close_location": 0.9},
            {"open": 102.5, "high": 102.8, "low": 101.2, "close": 101.5, "body_atr": -0.8, "close_location": 0.1},
        ]
    )
    assert generate_corpus_candidates(frame, "BTCUSDT") == []


def test_outside_bar_sweeping_both_sides_is_not_ordered_from_ohlc() -> None:
    frame = _features(
        [
            {"high": 104, "low": 96, "close": 100},
            {"high": 106, "low": 89, "close": 100},
            {"open": 100, "high": 104, "low": 96, "close": 100},
        ]
    )
    assert generate_corpus_candidates(frame, "BTCUSDT") == []
