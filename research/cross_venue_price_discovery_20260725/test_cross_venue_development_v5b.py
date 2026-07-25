from __future__ import annotations

import json
from pathlib import Path

import pytest

import cross_venue_development_v5b as development


def write_pilot(path: Path, **overrides) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "causal_version": 5,
        "causal_engine_version": "5B",
        "v1_v2_v3_v4_v4b_v5_outputs_admissible": False,
        "funding_boundary_contract": "prospective eight-hour settlement exclusion",
    }
    payload.update(overrides)
    (path / "PILOT_RESULT.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def test_valid_v5b_pilot_is_accepted(tmp_path: Path) -> None:
    payload = development.validate_pilot_v5b(write_pilot(tmp_path / "valid"))
    assert payload["causal_engine_version"] == "5B"


@pytest.mark.parametrize(
    "overrides",
    [
        {"causal_version": 4},
        {"causal_engine_version": "5"},
        {"v1_v2_v3_v4_v4b_v5_outputs_admissible": True},
        {"funding_boundary_contract": ""},
    ],
)
def test_non_v5b_pilot_is_rejected(tmp_path: Path, overrides: dict) -> None:
    with pytest.raises(ValueError):
        development.validate_pilot_v5b(write_pilot(tmp_path / "invalid", **overrides))
