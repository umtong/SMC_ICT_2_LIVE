from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from system.canonical_adapter import causal_asof_join  # noqa: E402
from system.coarse import CoarseEventReplay, CoarseExecutionConfig  # noqa: E402
from system.core import EventCandidate, EventFamily, RiskConfig  # noqa: E402
from system.model import ChronologicalEventModel, ScoredCandidate  # noqa: E402
from system.policy import GlobalSlotPolicy  # noqa: E402


class _CaptureClassifier:
    classes_ = np.asarray([0, 1])

    def __init__(self) -> None:
        self.last: pd.DataFrame | None = None

    def predict_proba(self, values: pd.DataFrame) -> np.ndarray:
        self.last = values.copy()
        return np.asarray([[0.4, 0.6]])


class _CaptureRegressor:
    def predict(self, values: pd.DataFrame) -> np.ndarray:
        return np.asarray([0.5])


class _IdentityCalibrator:
    def predict(self, values: list[float]) -> np.ndarray:
        return np.asarray(values, dtype=float)


def test_model_scoring_uses_same_structural_features_as_training() -> None:
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
        {"atr_fraction": 0.01},
    )
    win = _CaptureClassifier()
    fill = _CaptureClassifier()
    model = ChronologicalEventModel()
    model.feature_names = [
        "atr_fraction",
        "side",
        "raw_reward_risk",
        "family_liquidity_sweep",
        "symbol_btc",
    ]
    model.win_model = win
    model.r_model = _CaptureRegressor()
    model.fill_model = fill
    model.calibrator = _IdentityCalibrator()
    model._fitted = True
    model.score(event, risk_fraction=0.01, winner_net_r=2.0, loser_net_r=-1.0, fixed_cost_fraction=0.0)
    assert win.last is not None
    row = win.last.iloc[0]
    assert row["atr_fraction"] == 0.01
    assert row["side"] == 1.0
    assert row["raw_reward_risk"] == 3.0
    assert row["family_liquidity_sweep"] == 1.0
    assert row["symbol_btc"] == 1.0


def test_canonical_asof_join_normalizes_nullable_integer_keys() -> None:
    decision_times = pd.to_datetime(["2023-01-01T00:01:00Z", "2023-01-01T00:02:00Z"])
    base = pd.DataFrame(
        {
            "available_at_ms": pd.array([1672531260000, 1672531320000], dtype="Int64"),
            "close": [100.0, 101.0],
        },
        index=decision_times,
    )
    auxiliary = pd.DataFrame(
        {
            "available_at_ms": np.asarray([1672531200000, 1672531290000], dtype="int64"),
            "open_interest": [1.0, 2.0],
        },
        index=pd.to_datetime(["2023-01-01T00:00:00Z", "2023-01-01T00:01:30Z"]),
    )
    joined = causal_asof_join(base, auxiliary)
    assert joined["available_at_ms"].dtype == "int64"
    assert joined["open_interest"].tolist() == [1.0, 2.0]
    assert "source_timestamp" not in joined.columns

    second_auxiliary = pd.DataFrame(
        {
            "available_at_ms": np.asarray([1672531200000, 1672531290000], dtype="int64"),
            "funding_rate": [0.0001, 0.0002],
        },
        index=pd.to_datetime(["2023-01-01T00:00:00Z", "2023-01-01T00:01:30Z"]),
    )
    joined_twice = causal_asof_join(joined, second_auxiliary)
    assert joined_twice["funding_rate"].tolist() == [0.0001, 0.0002]
    assert "source_timestamp" not in joined_twice.columns


def test_coarse_replay_cannot_use_barrier_after_evaluation_cutoff() -> None:
    starts = pd.to_datetime(
        [
            "2023-01-01T00:01:00Z",
            "2023-01-01T23:59:00Z",
            "2023-01-02T00:01:00Z",
        ]
    )
    availability = starts + pd.Timedelta(minutes=1)
    frame = pd.DataFrame(
        {
            "bar_start": starts,
            "open": [100.0, 101.0, 101.0],
            "high": [101.0, 102.0, 111.0],
            "low": [99.0, 100.0, 100.0],
            "close": [100.0, 101.0, 110.0],
            "mark_close": [100.0, 101.0, 110.0],
            "spread_bps": 0.0,
        },
        index=availability,
    )
    event = EventCandidate(
        pd.Timestamp("2023-01-01T00:00:00Z"),
        "BTCUSDT",
        EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        1,
        100.0,
        100.0,
        90.0,
        110.0,
        95.0,
        {},
    )
    scored = ScoredCandidate(event, 0.7, 1.0, 0.1, 0.01, 0.01)
    account = CoarseEventReplay(
        {"BTCUSDT": frame},
        CoarseExecutionConfig(
            maker_fee_rate=0.0,
            taker_fee_rate=0.0,
            market_slippage_bps=0.0,
            stop_slippage_bps=0.0,
            minimum_spread_bps=0.0,
        ),
    ).run(
        [scored],
        GlobalSlotPolicy(0.55),
        RiskConfig(0.01, 5.0, 0.001),
        pd.Timestamp("2023-01-01T00:00:00Z"),
        pd.Timestamp("2023-01-02T00:00:00Z"),
    )
    assert len(account.closed_trades) == 0
    assert account.position is not None
    assert account.position.opened_at == pd.Timestamp("2023-01-01T00:01:00Z")
    assert account.cash == 10000.0
