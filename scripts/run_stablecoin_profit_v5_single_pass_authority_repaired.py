from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

import run_stablecoin_profit_v5_single_pass_authority as base

CLAIM_ID = base.CLAIM_ID
RESULT_ID = base.RESULT_ID
CORRECTION_ID = "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-STRICT-FIXTURE-ALIGNMENT-003"
CORRECTION_PATH = (
    Path(__file__).resolve().parents[1]
    / "research"
    / "execution"
    / "stablecoin_profit_v5_20260727"
    / "EXECUTION_CORRECTION_009_STRICT_FIXTURE_ALIGNMENT_BEFORE_OUTCOME.json"
)
_SOURCE_OLD = "authority.base."
_SOURCE_NEW = "authority.base.auth."
_EXPECTED_SOURCE_REFERENCES = 4
_TEST_OLD = '    assert int(rows.iloc[0]["completed_feature_index"]) == entry_index - 1\n'
_TEST_NEW = '''    decision_ms = int(events.iloc[0]["available_timestamp_12"]) * 1_000
    expected_completed = int(
        np.searchsorted(
            base_frame["open_time_ms"].to_numpy(np.int64) + 60_000,
            decision_ms,
            side="right",
        )
        - 1
    )
    assert int(rows.iloc[0]["completed_feature_index"]) == expected_completed
'''
_GAP_OLD = '''    gap_trade = strict_trade_from_row(
        changed_row,
        0.99,
        24.0,
'''
_GAP_NEW = '''    gap_trade = strict_trade_from_row(
        changed_row,
        1.0,
        24.0,
'''


def _load_correction() -> dict[str, Any]:
    payload = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    if payload.get("correction_id") != CORRECTION_ID:
        raise AssertionError("stablecoin execution correction identity changed")
    if payload.get("recorded_before_source_or_market_outcome") is not True:
        raise AssertionError("stablecoin execution correction was not outcome-sealed")
    if payload.get("scientific_contract_changed") is not False:
        raise AssertionError("scientific contract may not change in execution repair")
    if payload.get("runtime_engine_changed") is not False:
        raise AssertionError("runtime engine may not change in fixture repair")
    return payload


def _replace_exact(path: Path, old: str, new: str, expected: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    observed = text.count(old)
    if observed != expected:
        raise RuntimeError(
            f"expected {expected} frozen occurrence(s) in {path}, observed {observed}"
        )
    if new in text:
        raise RuntimeError(f"replacement already present before overlay in {path}")
    path.write_text(text.replace(old, new, expected), encoding="utf-8")


def repair_materialized_source(repository: Path) -> Path:
    """Repair only frozen source self-test namespaces in a temporary checkout."""
    _load_correction()
    path = (
        repository
        / "research"
        / "ml_stablecoin_issuance_20260726"
        / "run_pinned_snapshot_source.py"
    )
    _replace_exact(
        path,
        _SOURCE_OLD,
        _SOURCE_NEW,
        expected=_EXPECTED_SOURCE_REFERENCES,
    )
    return path


def repair_materialized_strict_fixtures(repository: Path) -> tuple[Path, Path]:
    """Align two stale pre-network fixtures with the already-frozen runtime rules."""
    _load_correction()
    causal_test = (
        repository
        / "research"
        / "ml_stablecoin_issuance_economic_20260726"
        / "test_run_causal.py"
    )
    strict_guard = (
        repository
        / "sourcefix"
        / "ml_stablecoin_causal_guard_20260726"
        / "strict_guard.py"
    )
    _replace_exact(causal_test, _TEST_OLD, _TEST_NEW)
    _replace_exact(strict_guard, _GAP_OLD, _GAP_NEW)
    return causal_test, strict_guard


def execute(work_dir: Path, publish_dir: Path) -> int:
    """Run the unchanged authority with pre-outcome execution/fixture overlays."""
    _load_correction()
    original_materialize: Callable[..., Any] = base.v4auth.materialize

    def materialize_with_repair(
        sha: str, paths: list[str], repository: Path
    ) -> None:
        original_materialize(sha, paths, repository)
        repaired_paths: list[str] = []
        if sha == base.v4auth.SOURCE_SHA:
            repaired_paths.append(str(repair_materialized_source(repository)))
        if sha == base.v4auth.STRICT_SHA:
            repaired_paths.extend(
                str(path) for path in repair_materialized_strict_fixtures(repository)
            )
        if repaired_paths:
            print(
                "STABLECOIN_V5_EXECUTION_REPAIR",
                json.dumps(
                    {
                        "correction_id": CORRECTION_ID,
                        "paths": repaired_paths,
                        "runtime_engine_changed": False,
                        "scientific_contract_changed": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    base.v4auth.materialize = materialize_with_repair
    try:
        return base.execute(work_dir, publish_dir)
    finally:
        base.v4auth.materialize = original_materialize


def _failure_payload(error: Exception) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "result_id": RESULT_ID,
        "status": "EXECUTION_FAILURE_NOT_SCIENTIFIC_RESULT",
        "correction_id": CORRECTION_ID,
        "error_type": type(error).__name__,
        "error": repr(error),
        "traceback": traceback.format_exc(),
        "source_sha": base.v4auth.SOURCE_SHA,
        "strict_sha": base.v4auth.STRICT_SHA,
        "profit_first_correction_id": base.PROFIT_CORRECTION,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--publish-dir", type=Path, required=True)
    args = parser.parse_args()
    work_dir = args.work_dir.resolve()
    publish_dir = args.publish_dir.resolve()
    try:
        return execute(work_dir, publish_dir)
    except Exception as error:
        publish_dir.mkdir(parents=True, exist_ok=True)
        failure = _failure_payload(error)
        base.v4auth.write_json(publish_dir / "EXECUTION_FAILURE.json", failure)
        base.v4auth.freeze_hashes(publish_dir)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
