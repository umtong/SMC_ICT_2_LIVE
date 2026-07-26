from __future__ import annotations

import math

import numpy as np

import run


def test_prior_channel_excludes_current_bar():
    frame = run.synthetic_hourly(300)
    features = run.feature_frame(frame)
    i = run.ENTRY_LOOKBACK
    assert math.isclose(
        float(features["channel_high"].iloc[i]),
        float(frame["high"].iloc[:i].max()),
    )


def test_gap_resets_rolling_horizon_without_imputation():
    frame = run.synthetic_hourly(300)
    frame.iloc[150, frame.columns.get_loc("valid")] = False
    frame.iloc[
        150, frame.columns.get_indexer(["open", "high", "low", "close", "volume"])
    ] = np.nan
    features = run.feature_frame(frame)
    assert features["ret24"].iloc[151:175].isna().all()
    assert np.isnan(features["channel_high"].iloc[175])


def test_stop_is_checked_before_channel_exit():
    frame = run.synthetic_hourly(250)
    features = run.feature_frame(frame)
    entry_i = 200
    entry = float(frame["open"].iloc[entry_i])
    stop = entry * 0.99
    frame.iloc[entry_i, frame.columns.get_loc("low")] = stop * 0.99
    features.iloc[entry_i, features.columns.get_loc("exit_low")] = entry * 1.01
    exit_i, exit_price, reason = run.exit_path(
        frame, features, entry_i, entry, 1, stop
    )
    assert exit_i == entry_i
    assert reason == "stop"
    assert math.isclose(exit_price, stop)


def test_risk_search_is_not_defensively_capped():
    assert max(run.RISK_GRID) == 0.60
    assert max(run.CAP_GRID) == 100.0


def test_2024_source_is_gated():
    try:
        run.month_url("BTCUSDT", 2024, 1, allow_2024=False)
    except ValueError:
        return
    raise AssertionError("sealed 2024 source was opened")


def test_model_feature_contract_is_fixed():
    assert len(run.FEATURE_COLUMNS) == 19
    assert len(set(run.FEATURE_COLUMNS)) == len(run.FEATURE_COLUMNS)
