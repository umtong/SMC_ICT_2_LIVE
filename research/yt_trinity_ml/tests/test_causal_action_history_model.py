from __future__ import annotations

import numpy as np
import pandas as pd

from system.causal_action_history_model import (
    ExplicitHistoryActionValueModel,
    HistoryActionModelConfig,
)


def _period_rows(start: str, count: int, action: str, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    activation = pd.date_range(start, periods=count, freq="12h", tz="UTC")
    quality = rng.uniform(-1.0, 1.0, count)
    passive = action == "EARLY_PASSIVE"
    fill_probability = 0.55 + 0.25 * quality if passive else np.ones(count)
    filled = (rng.random(count) < fill_probability).astype(int) if passive else np.ones(count, dtype=int)
    conditional = 0.25 + 0.9 * quality + rng.normal(0.0, 0.35, count)
    net_r = np.where(filled == 1, conditional, 0.0)
    return pd.DataFrame(
        {
            "activation": activation,
            "event_end": activation + pd.Timedelta(hours=3),
            "action": action,
            "filled": filled,
            "net_budget_r": net_r,
            "quality": quality,
            "passive_depth_fraction": 0.5 if passive else -1.0,
        }
    )


def _base_calibration() -> tuple[pd.DataFrame, pd.DataFrame]:
    base = pd.concat(
        [
            _period_rows("2021-01-01", 300, "EARLY_PASSIVE", 1),
            _period_rows("2021-01-01", 300, "CONFIRMED_MARKET", 2),
        ],
        ignore_index=True,
    )
    calibration = pd.concat(
        [
            _period_rows("2023-01-01", 120, "EARLY_PASSIVE", 3),
            _period_rows("2023-01-01", 120, "CONFIRMED_MARKET", 4),
        ],
        ignore_index=True,
    )
    return base, calibration


def _model() -> ExplicitHistoryActionValueModel:
    base, calibration = _base_calibration()
    return ExplicitHistoryActionValueModel(
        HistoryActionModelConfig(
            min_samples_leaf=15,
            max_iter=120,
            minimum_base_rows=100,
            minimum_outcome_rows=40,
            lower_confidence_penalty=0.10,
        )
    ).fit(base, calibration, ["quality", "passive_depth_fraction"])


def test_explicit_base_and_calibration_counts_are_preserved() -> None:
    model = _model()
    diagnostics = model.diagnostics()["actions"]
    assert diagnostics["EARLY_PASSIVE"]["base_rows"] == 300
    assert diagnostics["EARLY_PASSIVE"]["calibration_rows"] == 120
    assert diagnostics["CONFIRMED_MARKET"]["base_rows"] == 300
    assert diagnostics["CONFIRMED_MARKET"]["calibration_rows"] == 120


def test_future_selection_rows_cannot_change_frozen_model() -> None:
    base, calibration = _base_calibration()
    config = HistoryActionModelConfig(
        min_samples_leaf=15,
        max_iter=120,
        minimum_base_rows=100,
        minimum_outcome_rows=40,
        lower_confidence_penalty=0.10,
    )
    first = ExplicitHistoryActionValueModel(config).fit(
        base, calibration, ["quality", "passive_depth_fraction"]
    )
    future = _period_rows("2023-07-01", 500, "EARLY_PASSIVE", 99)
    second = ExplicitHistoryActionValueModel(config).fit(
        base.copy(), calibration.copy(), ["quality", "passive_depth_fraction"]
    )
    query = future.head(20).copy()
    left = first.predict(query)
    right = second.predict(query)
    assert first.fingerprint() == second.fingerprint()
    pd.testing.assert_frame_equal(left, right)


def test_prediction_does_not_read_realized_fill_label() -> None:
    model = _model()
    query = pd.DataFrame(
        [
            {
                "action": "EARLY_PASSIVE",
                "filled": 0,
                "quality": 0.4,
                "passive_depth_fraction": 0.5,
            },
            {
                "action": "EARLY_PASSIVE",
                "filled": 1,
                "quality": 0.4,
                "passive_depth_fraction": 0.5,
            },
        ]
    )
    scored = model.predict(query)
    assert scored.loc[0, "fill_probability"] == scored.loc[1, "fill_probability"]
    assert scored.loc[0, "lower_confidence_net_r"] == scored.loc[1, "lower_confidence_net_r"]


def test_passive_and_market_actions_keep_separate_heads() -> None:
    model = _model()
    query = pd.DataFrame(
        [
            {
                "action": "EARLY_PASSIVE",
                "filled": 0,
                "quality": 0.6,
                "passive_depth_fraction": 0.5,
            },
            {
                "action": "CONFIRMED_MARKET",
                "filled": 1,
                "quality": 0.6,
                "passive_depth_fraction": -1.0,
            },
        ]
    )
    scored = model.predict(query)
    assert set(model.heads) == {"CONFIRMED_MARKET", "EARLY_PASSIVE"}
    assert scored.loc[0, "fill_probability"] < 1.0
    assert scored.loc[1, "fill_probability"] == 1.0


def test_fingerprint_binds_exact_training_and_calibration_content() -> None:
    base, calibration = _base_calibration()
    config = HistoryActionModelConfig(
        min_samples_leaf=15, max_iter=120, minimum_base_rows=100,
        minimum_outcome_rows=40, lower_confidence_penalty=0.10,
    )
    original = ExplicitHistoryActionValueModel(config).fit(
        base, calibration, ["quality", "passive_depth_fraction"]
    )
    changed_base = base.copy()
    changed_base.loc[0, "quality"] = float(changed_base.loc[0, "quality"]) + 0.123456789
    changed = ExplicitHistoryActionValueModel(config).fit(
        changed_base, calibration.copy(), ["quality", "passive_depth_fraction"]
    )
    assert original.base_rows_digest != changed.base_rows_digest
    assert original.calibration_rows_digest == changed.calibration_rows_digest
    assert original.fingerprint() != changed.fingerprint()


def test_row_order_does_not_change_model_input_digest() -> None:
    base, calibration = _base_calibration()
    config = HistoryActionModelConfig(
        min_samples_leaf=15, max_iter=120, minimum_base_rows=100,
        minimum_outcome_rows=40, lower_confidence_penalty=0.10,
    )
    first = ExplicitHistoryActionValueModel(config).fit(
        base, calibration, ["quality", "passive_depth_fraction"]
    )
    second = ExplicitHistoryActionValueModel(config).fit(
        base.sample(frac=1.0, random_state=9).reset_index(drop=True),
        calibration.sample(frac=1.0, random_state=10).reset_index(drop=True),
        ["quality", "passive_depth_fraction"],
    )
    assert first.base_rows_digest == second.base_rows_digest
    assert first.calibration_rows_digest == second.calibration_rows_digest
