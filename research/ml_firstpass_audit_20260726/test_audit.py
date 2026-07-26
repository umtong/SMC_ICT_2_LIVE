from __future__ import annotations

import pytest

from audit import (
    FirstPassageLabel,
    choose_cost_adjusted_action,
    first_passage_label,
    validate_chronology,
    validate_manifest,
    validate_nonoverlapping_ledger,
)


def test_first_passage_ambiguous_is_explicit() -> None:
    outcome = first_passage_label([102.0], [98.0], 101.0, 99.0)
    assert outcome.label == FirstPassageLabel.AMBIGUOUS
    assert outcome.offset == 0


def test_cost_can_force_flat() -> None:
    decision = choose_cost_adjusted_action(
        p_upper_first=0.55,
        p_lower_first=0.45,
        upper_distance_bps=20.0,
        lower_distance_bps=20.0,
        roundtrip_cost_bps=12.0,
    )
    assert decision.action == "FLAT"


def test_calibration_must_be_out_of_train() -> None:
    with pytest.raises(ValueError, match="overlaps"):
        validate_chronology(
            {
                "train": {"start": "2022-01-01T00:00:00Z", "end": "2022-09-30T23:59:59Z"},
                "calibration": {"start": "2022-09-01T00:00:00Z", "end": "2022-10-31T23:59:59Z"},
                "confirmation": {"start": "2022-11-01T00:00:00Z", "end": "2022-12-31T23:59:59Z"},
                "development": {"start": "2023-01-01T00:00:00Z", "end": "2023-12-31T23:59:59Z"},
            }
        )


def test_manifest_rejects_model_grid() -> None:
    manifest = {
        "claim_id": "CLM-20260726-1703-ML-LIQUIDITY-DRAW-001",
        "model_family_count": 2,
        "hyperparameter_candidate_count": 1,
        "economic_decision_rule_count": 1,
        "one_global_slot": True,
        "2024_opened": False,
        "orders_submitted": False,
        "partitions": {
            "train": {"start": "2022-01-01T00:00:00Z", "end": "2022-06-30T23:59:59Z"},
            "calibration": {"start": "2022-07-01T00:00:00Z", "end": "2022-09-30T23:59:59Z"},
            "confirmation": {"start": "2022-10-01T00:00:00Z", "end": "2022-12-31T23:59:59Z"},
            "development": {"start": "2023-01-01T00:00:00Z", "end": "2023-12-31T23:59:59Z"},
        },
    }
    with pytest.raises(ValueError, match="one model family"):
        validate_manifest(manifest)


def test_global_overlap_is_rejected() -> None:
    rows = [
        {
            "symbol": "BTCUSDT",
            "action": "LONG",
            "entry_ts": "2023-01-01T00:00:00Z",
            "exit_ts": "2023-01-01T00:10:00Z",
        },
        {
            "symbol": "ETHUSDT",
            "action": "SHORT",
            "entry_ts": "2023-01-01T00:09:00Z",
            "exit_ts": "2023-01-01T00:20:00Z",
        },
    ]
    with pytest.raises(ValueError, match="overlap"):
        validate_nonoverlapping_ledger(rows)
