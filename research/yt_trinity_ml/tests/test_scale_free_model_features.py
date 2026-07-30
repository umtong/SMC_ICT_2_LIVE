from __future__ import annotations

import numpy as np
import pandas as pd

from system.core import EventCandidate, EventFamily, FeatureConfig, build_causal_features
from system.model import _eligible_model_feature_name, candidate_model_features


def _bars(count: int = 240) -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=count, freq="5min", tz="UTC")
    close = 100.0 + np.linspace(0.0, 3.0, count)
    return pd.DataFrame(
        {
            "open": np.r_[close[0], close[:-1]],
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": np.linspace(100.0, 200.0, count),
            "premium_close": np.linspace(-0.0002, 0.0003, count),
        },
        index=index,
    )


def test_premium_index_is_rate_not_contract_price() -> None:
    frame = _bars()
    features = build_causal_features(
        frame,
        FeatureConfig(atr_window=3, fast_ema=3, slow_ema=5, long_ema=8, volume_window=5),
    )
    np.testing.assert_allclose(
        features["premium_bps"].to_numpy(),
        frame["premium_close"].to_numpy() * 10_000.0,
    )
    assert features["premium_atr"].isna().all()
    assert features["premium_rate_z"].notna().sum() > 100


def test_candidate_feature_contract_removes_absolute_price_identity() -> None:
    event = EventCandidate(
        pd.Timestamp("2023-01-01T00:00:00Z"),
        "BTCUSDT",
        EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        1,
        100.0,
        100.0,
        98.0,
        106.0,
        99.0,
        {
            "close": 100.0,
            "atr": 2.0,
            "ema_fast": 99.0,
            "previous_day_high": 110.0,
            "equal_high_liquidity": 109.0,
            "premium_atr": -861.0,
            "sweep_depth_atr": 0.7,
            "premium_bps": 1.2,
            "premium_rate_z": 0.4,
            "liquidity_quality": 6.0,
            "x1": 3.0,
        },
    )
    values = candidate_model_features(event)
    for forbidden in (
        "close",
        "atr",
        "ema_fast",
        "previous_day_high",
        "equal_high_liquidity",
        "premium_atr",
    ):
        assert forbidden not in values
    for required in (
        "sweep_depth_atr",
        "premium_bps",
        "premium_rate_z",
        "liquidity_quality",
        "x1",
        "raw_reward_risk",
        "symbol_btc",
    ):
        assert required in values


def test_feature_name_filter_keeps_normalized_geometry() -> None:
    assert not _eligible_model_feature_name("htf_4h_last_swing_high")
    assert not _eligible_model_feature_name("bull_fvg_lower")
    assert not _eligible_model_feature_name("available_at_ms")
    assert _eligible_model_feature_name("distance_previous_day_high_atr")
    assert _eligible_model_feature_name("htf_bias_score")
    assert _eligible_model_feature_name("near_equal_high")
    assert _eligible_model_feature_name("raw_structural_reward_risk")
