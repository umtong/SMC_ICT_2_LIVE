from __future__ import annotations

import numpy as np
import pandas as pd

from system.causal_action_candidates import generate_causal_action_candidates


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


def _armed_without_retest() -> pd.DataFrame:
    return _features(
        [
            {"high": 101, "low": 99, "close": 100},
            {"high": 102, "low": 99, "close": 101},
            {"high": 104, "low": 100, "close": 103},
            {
                "open": 104,
                "high": 106,
                "low": 102,
                "close": 104,
                "micro_last_swing_low": 100,
            },
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
                "micro_last_swing_low": 100,
            },
        ]
    )


def test_pd_array_arming_emits_passive_without_future_retest() -> None:
    frame = _armed_without_retest()
    events, diagnostics = generate_causal_action_candidates(frame, "BTCUSDT")
    passive = [row for row in events if row.feature_row["action_candidate_early_passive"] == 1.0]
    market = [row for row in events if row.feature_row["action_candidate_confirmed_market"] == 1.0]
    assert len(passive) == 1
    assert market == []
    assert passive[0].timestamp == frame.index[4]
    assert passive[0].entry_reference == 102.5
    assert passive[0].target_reference == 95.0
    assert diagnostics["causal_passive_actions"] == 1


def test_later_rejection_adds_separate_market_action() -> None:
    frame = _armed_without_retest()
    frame.loc[frame.index[-1] + pd.Timedelta(minutes=5)] = {
        **frame.iloc[-1].to_dict(),
        "open": 102.4,
        "high": 102.8,
        "low": 101.5,
        "close": 101.6,
        "body_atr": -0.8,
        "range_atr": 1.3,
        "close_location": 0.08,
    }
    frame = frame.sort_index()
    events, diagnostics = generate_causal_action_candidates(frame, "BTCUSDT")
    passive = [row for row in events if row.feature_row["action_candidate_early_passive"] == 1.0]
    market = [row for row in events if row.feature_row["action_candidate_confirmed_market"] == 1.0]
    assert len(passive) == 1
    assert len(market) == 1
    assert passive[0].timestamp < market[0].timestamp
    assert passive[0].entry_reference != market[0].entry_reference
    assert diagnostics["causal_passive_actions"] == 1
    assert diagnostics["confirmed_market_actions"] == 1
