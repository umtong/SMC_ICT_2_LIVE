from __future__ import annotations

import json
from pathlib import Path

import causal_guard


def test_strict_preentry_self_test() -> None:
    causal_guard.self_test()


def test_legacy_synthetic_boundary_exit_is_fatal(tmp_path: Path) -> None:
    compact = {
        "claim_id": causal_guard.CLAIM_ID,
        "status": "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1",
        "development_gate": {"all": True},
        "development_opened": True,
        "official_2024h1_opened": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    full = {
        **compact,
        "development": {
            "costs": {
                "24": {
                    "trade_ledger": [
                        {
                            "event_id": "legacy-event",
                            "symbol": "ETHUSDT",
                            "exit_reason": "SOURCE_BOUNDARY",
                        }
                    ]
                }
            }
        },
    }
    (tmp_path / "RESULT.json").write_text(json.dumps(compact))
    (tmp_path / "FULL_RESULT.json").write_text(json.dumps(full))
    guard = causal_guard.audit_result(tmp_path)
    corrected = json.loads((tmp_path / "RESULT.json").read_text())
    assert guard["fatal_validity_violation"] is True
    assert guard["legacy_source_boundary_paths"]
    assert corrected["status"] == "PRE2024_INVALID_STRICT_CAUSAL_GUARD"
    assert corrected["development_gate"]["all"] is False
    assert (tmp_path / "SHA256SUMS.txt").is_file()


def test_correction_record_is_parseable() -> None:
    path = Path(__file__).with_name(
        "CORRECTION_002_PREENTRY_INFORMATION_BOUNDARY_BEFORE_OUTCOME.json"
    )
    payload = json.loads(path.read_text())
    assert payload["correction_id"] == causal_guard.CORRECTION_ID
    assert payload["recorded_before_market_download"] is True
    assert payload["frozen_fix"]["decision_reference_price"].startswith(
        "last completed close"
    )
