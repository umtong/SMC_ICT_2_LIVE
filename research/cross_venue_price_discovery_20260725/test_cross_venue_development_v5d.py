from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import cross_venue_basis_v5d as basis_v5d
import cross_venue_counterfactual_v5d as counterfactual
import cross_venue_development_v5d as development
import cross_venue_execution_v5d as v5d
import cross_venue_pilot as v1
import test_cross_venue_execution_v5d as fixtures


def write_pilot(path: Path, **overrides) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "causal_version": 5,
        "causal_engine_version": "5D",
        "v1_v2_v3_v4_v4b_v5_v5b_v5c_outputs_admissible": False,
        "funding_boundary_contract": "prospective settlement exclusion",
        "protective_stop_contract": "adverse stop fill",
        "source_continuity_contract": "segmented state",
        "execution_gap_contract": "bounded observable quotes",
        "exit_floor_contract": "no economic price floor",
        "drawdown_contract": "one chronological marked path",
        "pilot_day_denominator": "all preregistered pilot dates including zero-trade dates",
    }
    payload.update(overrides)
    (path / "PILOT_RESULT.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def passing_metrics() -> dict[float, dict]:
    base = {
        "terminal_account_loss": False,
        "n": 600,
        "trades_per_day_median": 20.0,
        "total_return": 0.20,
        "return_2022": 0.08,
        "return_2023": 0.10,
        "positive_day_fraction": 0.70,
        "top5_positive_share": 0.10,
        "profit_factor": 1.30,
        "maximum_drawdown": 0.10,
        "maximum_single_symbol_positive_pnl_share": 0.60,
        "top10pct_removed_return": None,
    }
    return {
        5.0: dict(base),
        7.5: dict(base, total_return=0.12),
        10.0: dict(base, total_return=0.05),
    }


def test_valid_v5d_pilot_is_accepted(tmp_path: Path) -> None:
    result = development.validate_pilot_v5d(write_pilot(tmp_path / "valid"))
    assert result["causal_engine_version"] == "5D"


@pytest.mark.parametrize(
    "overrides",
    [
        {"causal_engine_version": "5C"},
        {"v1_v2_v3_v4_v4b_v5_v5b_v5c_outputs_admissible": True},
        {"source_continuity_contract": ""},
        {"execution_gap_contract": ""},
        {"exit_floor_contract": ""},
        {"drawdown_contract": ""},
    ],
)
def test_incomplete_v5d_pilot_is_rejected(tmp_path: Path, overrides: dict) -> None:
    with pytest.raises(ValueError):
        development.validate_pilot_v5d(write_pilot(tmp_path / "invalid", **overrides))


def test_preliminary_gate_defers_only_counterfactual_top10() -> None:
    metrics = passing_metrics()
    assert development.preliminary_pass(metrics) is True
    metrics[5.0]["terminal_account_loss"] = True
    assert development.preliminary_pass(metrics) is False


def test_winner_keys_use_stable_event_identity() -> None:
    ledger = pd.DataFrame({
        "day": ["2022-01-01"] * 15,
        "symbol": ["BTCUSDT"] * 15,
        "family": ["f"] * 15,
        "decision_ms": list(range(15)),
        "side": [1] * 15,
        "account_return": [float(value) for value in range(15)],
    })
    removed = counterfactual.winner_keys(ledger)
    assert len(removed) == 2
    assert ("2022-01-01", "BTCUSDT", "f", 14, 1) in removed
    assert ("2022-01-01", "BTCUSDT", "f", 13, 1) in removed


def test_event_exclusion_releases_global_slot() -> None:
    basis_v5d.patch()
    v5d.patch_v5()
    day = "synthetic"
    frames = {
        (day, "A"): fixtures.execution_frame(),
        (day, "B"): fixtures.execution_frame(),
    }
    events = [
        v1.Event(day, "A", "f", 60_000, 1, 10.0, 0.0),
        v1.Event(day, "B", "f", 60_000, 1, 1.0, 0.0),
    ]
    baseline = v5d.simulate_fixed_day_v5(frames, events, fixtures.config())
    assert len(baseline) == 1 and baseline[0].symbol == "A"
    removed = {counterfactual.event_key(events[0])}
    replay = v5d.simulate_fixed_day_v5(
        frames,
        [item for item in events if counterfactual.event_key(item) not in removed],
        fixtures.config(),
    )
    assert len(replay) == 1 and replay[0].symbol == "B"
