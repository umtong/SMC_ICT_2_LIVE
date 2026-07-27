from __future__ import annotations

import numpy as np
import pandas as pd

from system.core import EventFamily, FeatureConfig
from system.corpus_alpha import build_corpus_features, generate_corpus_candidates


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
        "volume": 100.0,
        "atr": 1.0,
        "body_atr": 0.0,
        "range_atr": 2.0,
        "close_location": 0.5,
        "last_swing_high": 105.0,
        "last_swing_low": 95.0,
        "micro_last_swing_high": 103.0,
        "micro_last_swing_low": 97.0,
        "internal_high_5": 103.0,
        "internal_low_5": 97.0,
        "previous_day_high": 110.0,
        "previous_day_low": 90.0,
        "previous_week_high": 120.0,
        "previous_week_low": 80.0,
        "previous_1h_high": 104.0,
        "previous_1h_low": 96.0,
        "previous_4h_high": 108.0,
        "previous_4h_low": 92.0,
        "current_asia_high": np.nan,
        "current_asia_low": np.nan,
        "current_london_open_high": np.nan,
        "current_london_open_low": np.nan,
        "htf_1h_last_swing_high": np.nan,
        "htf_1h_last_swing_low": np.nan,
        "htf_4h_last_swing_high": np.nan,
        "htf_4h_last_swing_low": np.nan,
        "equal_high_liquidity": np.nan,
        "equal_low_liquidity": np.nan,
        "htf_bias_score": 0.0,
        "dealing_range_position": 0.5,
        "volume_z": 0.0,
        "bull_fvg_lower": np.nan,
        "bull_fvg_upper": np.nan,
        "bear_fvg_lower": np.nan,
        "bear_fvg_upper": np.nan,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows], index=index)


def test_corpus_features_do_not_change_when_future_is_appended() -> None:
    frame = _raw_bars()
    config = FeatureConfig(atr_window=5, fast_ema=5, slow_ema=8, long_ema=13, volume_window=5)
    short = build_corpus_features(frame.iloc[:400], config)
    long = build_corpus_features(frame, config)
    pd.testing.assert_frame_equal(short, long.loc[short.index], check_dtype=False)


def test_reversal_is_liquidity_to_displacement_to_pd_array_to_cisd() -> None:
    frame = _features(
        [
            {"high": 101, "low": 99, "close": 100},
            {"high": 102, "low": 99, "close": 101},
            {"high": 104, "low": 100, "close": 103},
            {"open": 104, "high": 106, "low": 102, "close": 104, "micro_last_swing_low": 100},
            {
                "open": 104,
                "high": 104.2,
                "low": 98,
                "close": 99,
                "body_atr": -5.0,
                "range_atr": 6.2,
                "close_location": 0.16,
                "bear_fvg_lower": 102,
                "bear_fvg_upper": 103,
                "last_swing_low": 95,
            },
            {
                "open": 102.0,
                "high": 102.7,
                "low": 101.8,
                "close": 102.4,
                "body_atr": 0.4,
                "range_atr": 0.9,
                "close_location": 0.67,
                "last_swing_low": 97,
            },
            {
                "open": 102.2,
                "high": 102.3,
                "low": 100.7,
                "close": 101.0,
                "body_atr": -1.2,
                "range_atr": 1.6,
                "close_location": 0.19,
                "last_swing_low": 97,
            },
        ]
    )
    events = generate_corpus_candidates(frame, "BTCUSDT")
    assert len(events) == 1
    event = events[0]
    assert event.timestamp == frame.index[6]
    assert event.family == EventFamily.LIQUIDITY_SWEEP_REVERSAL and event.side == -1
    assert event.stop_reference > 106
    assert event.target_reference == 95
    assert event.feature_row["pd_array_kind"] == 2
    assert event.feature_row["liquidity_quality"] >= 4
    assert event.feature_row["draw_target_quality"] >= 4


def test_first_mitigation_without_rejection_does_not_consume_valid_narrative() -> None:
    frame = _features(
        [
            {"high": 101, "low": 99, "close": 100},
            {"high": 102, "low": 99, "close": 101},
            {"high": 104, "low": 100, "close": 103},
            {"open": 104, "high": 106, "low": 102, "close": 104, "micro_last_swing_low": 100},
            {
                "open": 104,
                "high": 104.2,
                "low": 98,
                "close": 99,
                "body_atr": -5.0,
                "range_atr": 6.2,
                "close_location": 0.16,
                "bear_fvg_lower": 102,
                "bear_fvg_upper": 103,
            },
            {
                "open": 101.9,
                "high": 102.6,
                "low": 101.6,
                "close": 102.3,
                "body_atr": 0.4,
                "range_atr": 1.0,
                "close_location": 0.7,
            },
            {
                "open": 102.2,
                "high": 102.4,
                "low": 100.8,
                "close": 101.0,
                "body_atr": -1.2,
                "range_atr": 1.6,
                "close_location": 0.12,
            },
        ]
    )
    events = generate_corpus_candidates(frame, "BTCUSDT")
    assert len(events) == 1 and events[0].timestamp == frame.index[6]


def test_draw_on_liquidity_is_frozen_at_raid_not_chased_at_entry() -> None:
    frame = _features(
        [
            {"high": 101, "low": 99, "close": 100},
            {"high": 102, "low": 99, "close": 101},
            {"high": 104, "low": 100, "close": 103},
            {"open": 104, "high": 106, "low": 102, "close": 104, "micro_last_swing_low": 100, "last_swing_low": 95},
            {
                "open": 104,
                "high": 104.2,
                "low": 98,
                "close": 99,
                "body_atr": -5.0,
                "range_atr": 6.2,
                "close_location": 0.16,
                "bear_fvg_lower": 102,
                "bear_fvg_upper": 103,
                "last_swing_low": 97,
            },
            {
                "open": 102.4,
                "high": 102.8,
                "low": 101.5,
                "close": 101.6,
                "body_atr": -0.8,
                "range_atr": 1.3,
                "close_location": 0.08,
                "last_swing_low": 97,
            },
        ]
    )
    events = generate_corpus_candidates(frame, "BTCUSDT")
    assert len(events) == 1
    assert events[0].target_reference == 95


def test_target_taken_before_entry_structurally_invalidates_setup() -> None:
    frame = _features(
        [
            {"high": 101, "low": 99, "close": 100},
            {"high": 102, "low": 99, "close": 101},
            {"high": 104, "low": 100, "close": 103},
            {"open": 104, "high": 106, "low": 102, "close": 104, "micro_last_swing_low": 100},
            {
                "open": 104,
                "high": 104.2,
                "low": 98,
                "close": 99,
                "body_atr": -5.0,
                "range_atr": 6.2,
                "close_location": 0.16,
                "bear_fvg_lower": 102,
                "bear_fvg_upper": 103,
            },
            {"open": 99, "high": 100, "low": 94, "close": 96, "body_atr": -3.0, "range_atr": 6.0, "close_location": 0.33},
            {"open": 102.4, "high": 102.8, "low": 101.5, "close": 101.6, "body_atr": -0.8, "range_atr": 1.3, "close_location": 0.08},
        ]
    )
    assert generate_corpus_candidates(frame, "BTCUSDT") == []


def test_continuation_requires_first_close_break_displacement_and_pd_retest() -> None:
    frame = _features(
        [
            {"high": 101, "low": 98, "close": 100, "last_swing_high": 103},
            {"high": 102, "low": 99, "close": 101, "last_swing_high": 103},
            {
                "open": 101,
                "high": 105,
                "low": 101,
                "close": 104,
                "body_atr": 3.0,
                "range_atr": 4.0,
                "close_location": 0.75,
                "bull_fvg_lower": 100,
                "bull_fvg_upper": 101,
                "micro_last_swing_low": 98,
                "last_swing_high": 103,
                "previous_4h_high": 108,
                "htf_bias_score": 3,
            },
            {
                "open": 100.7,
                "high": 102,
                "low": 100.4,
                "close": 101.5,
                "body_atr": 0.8,
                "range_atr": 1.6,
                "close_location": 0.69,
                "last_swing_high": 103,
                "previous_4h_high": 108,
                "htf_bias_score": 3,
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


def test_outside_bar_sweeping_both_sides_is_not_ordered_from_ohlc() -> None:
    frame = _features(
        [
            {"high": 104, "low": 96, "close": 100},
            {"high": 106, "low": 89, "close": 100, "body_atr": 0.0, "range_atr": 17.0},
            {"open": 100, "high": 104, "low": 96, "close": 100},
        ]
    )
    assert generate_corpus_candidates(frame, "BTCUSDT") == []


def test_diagnostics_expose_implementation_funnel() -> None:
    from system.corpus_alpha import generate_corpus_candidates_with_diagnostics

    frame = _features(
        [
            {"high": 101, "low": 99, "close": 100},
            {"high": 102, "low": 99, "close": 101},
            {"high": 104, "low": 100, "close": 103},
            {"open": 104, "high": 106, "low": 102, "close": 104, "micro_last_swing_low": 100},
            {
                "open": 104,
                "high": 104.2,
                "low": 98,
                "close": 99,
                "body_atr": -5.0,
                "range_atr": 6.2,
                "close_location": 0.16,
                "bear_fvg_lower": 102,
                "bear_fvg_upper": 103,
            },
            {"open": 102.4, "high": 102.8, "low": 101.5, "close": 101.6, "body_atr": -0.8, "range_atr": 1.3, "close_location": 0.08},
        ]
    )
    events, diagnostics = generate_corpus_candidates_with_diagnostics(frame, "BTCUSDT")
    assert len(events) == 1
    assert diagnostics["external_liquidity_raids"] >= 1
    assert diagnostics["displacement_structure_confirmations"] >= 1
    assert diagnostics["pd_array_states_armed"] >= 1
    assert diagnostics["pd_array_first_mitigations"] >= 1
    assert diagnostics["entry_confirmations"] == 1
