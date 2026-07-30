from __future__ import annotations

import numpy as np
import pandas as pd

from system.causal_action_model import (
    GroupedActionModelConfig,
    GroupedCausalActionValueModel,
)


def _rows() -> pd.DataFrame:
    rng = np.random.default_rng(20260727)
    rows = []
    start = pd.Timestamp("2023-01-01T00:00:00Z")
    for action, base_r in (("EARLY_PASSIVE", 0.45), ("CONFIRMED_MARKET", -0.15)):
        for i in range(260):
            activation = start + pd.Timedelta(hours=6 * i)
            quality = rng.uniform(-1.0, 1.0)
            noise = rng.normal(0.0, 0.35)
            net_r = base_r + 0.9 * quality + noise
            rows.append(
                {
                    "activation": activation,
                    "event_end": activation + pd.Timedelta(hours=2),
                    "action": action,
                    "net_budget_r": net_r,
                    "quality": quality,
                    "passive_depth_fraction": 0.5 if action == "EARLY_PASSIVE" else -1.0,
                }
            )
    return pd.DataFrame(rows)


def test_grouped_heads_keep_order_actions_economically_separate() -> None:
    rows = _rows()
    model = GroupedCausalActionValueModel(
        GroupedActionModelConfig(
            min_samples_leaf=15,
            minimum_group_rows=100,
            max_iter=120,
            lower_confidence_penalty=0.10,
        )
    ).fit(rows, ["quality", "passive_depth_fraction"])
    query = pd.DataFrame(
        [
            {"action": "EARLY_PASSIVE", "quality": 0.5, "passive_depth_fraction": 0.5},
            {"action": "CONFIRMED_MARKET", "quality": 0.5, "passive_depth_fraction": -1.0},
        ]
    )
    scored = model.predict(query)
    assert set(model.heads) == {"CONFIRMED_MARKET", "EARLY_PASSIVE"}
    assert scored.loc[0, "expected_net_r"] > scored.loc[1, "expected_net_r"]
    assert scored.loc[0, "lower_confidence_net_r"] > scored.loc[1, "lower_confidence_net_r"]


def test_appending_future_rows_does_not_change_frozen_past_model() -> None:
    rows = _rows()
    cutoff = pd.Timestamp("2023-02-15T00:00:00Z")
    past = rows[pd.to_datetime(rows["event_end"], utc=True) < cutoff].copy()
    future = rows[pd.to_datetime(rows["event_end"], utc=True) >= cutoff].copy()
    config = GroupedActionModelConfig(
        min_samples_leaf=10,
        minimum_group_rows=60,
        max_iter=100,
        lower_confidence_penalty=0.10,
    )
    first = GroupedCausalActionValueModel(config).fit(
        past, ["quality", "passive_depth_fraction"]
    )
    second = GroupedCausalActionValueModel(config).fit(
        pd.concat([past, future]).loc[past.index],
        ["quality", "passive_depth_fraction"],
    )
    query = past.tail(20).copy()
    left = first.predict(query)
    right = second.predict(query)
    pd.testing.assert_frame_equal(left, right)


def test_lower_confidence_score_penalizes_uncertain_actions() -> None:
    rows = _rows()
    model = GroupedCausalActionValueModel(
        GroupedActionModelConfig(
            min_samples_leaf=15,
            minimum_group_rows=100,
            max_iter=120,
            lower_confidence_penalty=0.50,
        )
    ).fit(rows, ["quality", "passive_depth_fraction"])
    query = pd.DataFrame(
        [
            {"action": "EARLY_PASSIVE", "quality": 0.9, "passive_depth_fraction": 0.5},
            {"action": "EARLY_PASSIVE", "quality": 0.0, "passive_depth_fraction": 0.5},
        ]
    )
    scored = model.predict(query)
    assert (scored["lower_confidence_net_r"] <= scored["expected_net_r"]).all()
    assert scored.loc[0, "lower_confidence_net_r"] > scored.loc[1, "lower_confidence_net_r"]
