from __future__ import annotations

import json
from pathlib import Path

import pytest

import cross_venue_development_v5c as development


def write_pilot(path: Path, **overrides) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "causal_version": 5,
        "causal_engine_version": "5C",
        "v1_v2_v3_v4_v4b_v5_v5b_outputs_admissible": False,
        "funding_boundary_contract": "prospective eight-hour settlement exclusion",
        "protective_stop_contract": "adverse trigger extremum versus delayed quote",
        "pilot_day_denominator": "all preregistered pilot dates including zero-trade dates",
        "grid_alignment_contract": "decision, latency and hold are integer multiples of 100ms",
    }
    payload.update(overrides)
    (path / "PILOT_RESULT.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def test_valid_v5c_pilot_is_accepted(tmp_path: Path) -> None:
    payload = development.validate_pilot_v5c(write_pilot(tmp_path / "valid"))
    assert payload["causal_engine_version"] == "5C"


@pytest.mark.parametrize(
    "overrides",
    [
        {"causal_version": 4},
        {"causal_engine_version": "5B"},
        {"v1_v2_v3_v4_v4b_v5_v5b_outputs_admissible": True},
        {"funding_boundary_contract": ""},
        {"protective_stop_contract": ""},
        {"pilot_day_denominator": "active dates only"},
        {"grid_alignment_contract": ""},
    ],
)
def test_non_v5c_pilot_is_rejected(tmp_path: Path, overrides: dict) -> None:
    with pytest.raises(ValueError):
        development.validate_pilot_v5c(write_pilot(tmp_path / "invalid", **overrides))
