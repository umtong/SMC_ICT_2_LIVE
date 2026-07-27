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


def test_causal_asof_join_normalizes_nullable_and_numpy_epoch_keys() -> None:
    base = pd.DataFrame(
        {
            "available_at_ms": pd.array([300_000, 600_000], dtype="Int64"),
            "close": [101.0, 102.0],
        },
        index=pd.to_datetime(["1970-01-01T00:05:00Z", "1970-01-01T00:10:00Z"]),
    )
    auxiliary = pd.DataFrame(
        {
            "available_at_ms": np.asarray([299_999, 600_001], dtype=np.int64),
            "mark_close": [100.5, 102.5],
        },
        index=pd.to_datetime(["1970-01-01T00:04:00Z", "1970-01-01T00:09:00Z"]),
    )

    joined = causal_asof_join(base, auxiliary)

    assert joined["available_at_ms"].dtype == np.dtype("int64")
    assert joined["mark_close"].tolist() == [100.5, 100.5]


def test_causal_asof_join_preserves_independent_source_time_per_stream() -> None:
    base = pd.DataFrame(
        {
            "available_at_ms": np.asarray([300_000, 600_000], dtype=np.int64),
            "close": [101.0, 102.0],
        },
        index=pd.to_datetime(["1970-01-01T00:05:00Z", "1970-01-01T00:10:00Z"]),
    )
    mark = pd.DataFrame(
        {
            "available_at_ms": np.asarray([299_000, 599_000], dtype=np.int64),
            "mark_close": [100.5, 101.5],
        },
        index=pd.DatetimeIndex(
            pd.to_datetime(["1970-01-01T00:04:00Z", "1970-01-01T00:09:00Z"]),
            name="timestamp",
        ),
    )
    index = pd.DataFrame(
        {
            "available_at_ms": np.asarray([298_000, 598_000], dtype=np.int64),
            "index_close": [100.4, 101.4],
        },
        index=pd.DatetimeIndex(
            pd.to_datetime(["1970-01-01T00:03:00Z", "1970-01-01T00:08:00Z"]),
            name="timestamp",
        ),
    )

    joined = causal_asof_join(causal_asof_join(base, mark), index)

    assert "mark_close_source_timestamp" in joined.columns
    assert "index_close_source_timestamp" in joined.columns
    assert "source_timestamp" not in joined.columns
    assert joined["mark_close"].tolist() == [100.5, 101.5]
    assert joined["index_close"].tolist() == [100.4, 101.4]
    assert joined["mark_close_source_timestamp"].iloc[0] == pd.Timestamp("1970-01-01T00:04:00Z")
    assert joined["index_close_source_timestamp"].iloc[0] == pd.Timestamp("1970-01-01T00:03:00Z")
