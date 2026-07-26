from __future__ import annotations

import numpy as np
import pandas as pd

from .common import FEATURE_COLUMNS
from .strategy import fit_model, score_candidates
from .strategy_missing_aware import (
    PATCH_COUNT,
    _patched_source,
    availability_diagnostics,
)


def test_complete_case_gate_is_replaced_exactly_once() -> None:
    assert PATCH_COUNT == 1
    assert "below 90%" not in _patched_source
    assert "metric_gate_correction_id" in _patched_source
    assert "fillna" not in _patched_source


def test_selected_hgbt_fits_and_scores_structural_metric_nans() -> None:
    rng = np.random.default_rng(20260727)
    rows = 640
    frame = pd.DataFrame(
        rng.normal(size=(rows, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS
    )
    # Reproduce the source semantics that invalidated the old complete-case
    # gate: OI is dense, top-trader state is structurally sparse, and taker
    # state is less sparse. NaNs must remain NaNs for HGBT routing.
    frame.loc[np.arange(rows) % 4 == 0, "top_account_ls"] = np.nan
    frame.loc[np.arange(rows) % 4 == 1, "top_position_ls"] = np.nan
    frame.loc[np.arange(rows) % 9 == 0, "taker_buy_sell_ratio"] = np.nan
    frame.loc[np.arange(rows) % 7 == 0, "global_account_ls"] = np.nan
    frame["resolution"] = np.where(np.arange(rows) % 3 == 0, "target", "stop")

    complete_share = frame[
        ["open_interest_log", "top_position_ls", "taker_buy_sell_ratio"]
    ].notna().all(axis=1).mean()
    assert complete_share < 0.90

    contract = {
        "model": {
            "learning_rate": 0.06,
            "max_iter": 40,
            "max_leaf_nodes": 15,
            "min_samples_leaf": 20,
            "l2_regularization": 1.0,
            "early_stopping": False,
            "random_state": 20260727,
        }
    }
    model = fit_model(frame, contract)
    scored = score_candidates(model, frame.iloc[:32].copy())
    assert scored["probability"].between(0.0, 1.0).all()
    assert frame["top_position_ls"].isna().any()

    diagnostics = availability_diagnostics(frame)
    assert diagnostics["imputation_applied"] is False
    assert diagnostics["all_external_metric_share"] < 0.90
    assert diagnostics["any_external_metric_share"] == 1.0
