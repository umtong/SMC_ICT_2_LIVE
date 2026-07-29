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
CORRECTION_ID = "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-SOURCE-SELFTEST-AND-FAILURE-PATH-001"
CORRECTION_PATH = (
    Path(__file__).resolve().parents[1]
    / "research"
    / "execution"
    / "stablecoin_profit_v5_20260727"
    / "EXECUTION_CORRECTION_007_SOURCE_SELFTEST_AND_FAILURE_PATH_BEFORE_OUTCOME.json"
)
_OLD_SELF_TEST = "decoded = authority.base.decode_log("
_NEW_SELF_TEST = "decoded = authority.base.auth.decode_log("


def _load_correction() -> dict[str, Any]:
    payload = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    if payload.get("correction_id") != CORRECTION_ID:
        raise AssertionError("stablecoin execution correction identity changed")
    if payload.get("recorded_before_source_or_market_outcome") is not True:
        raise AssertionError("stablecoin execution correction was not outcome-sealed")
    if payload.get("scientific_contract_changed") is not False:
        raise AssertionError("scientific contract may not change in execution repair")
    return payload


def repair_materialized_source(repository: Path) -> Path:
    """Repair only the frozen source self-test namespace in a temporary checkout."""
    _load_correction()
    path = (
        repository
        / "research"
        / "ml_stablecoin_issuance_20260726"
        / "run_pinned_snapshot_source.py"
    )
    text = path.read_text(encoding="utf-8")
    observed = text.count(_OLD_SELF_TEST)
    if observed != 1:
        raise RuntimeError(
            "expected exactly one frozen self-test namespace reference, "
            f"observed {observed}"
        )
    if _NEW_SELF_TEST in text:
        raise RuntimeError("repaired self-test namespace already present before overlay")
    path.write_text(text.replace(_OLD_SELF_TEST, _NEW_SELF_TEST, 1), encoding="utf-8")
    return path


def execute(work_dir: Path, publish_dir: Path) -> int:
    """Run the unchanged authority with a pre-outcome execution-only overlay."""
    _load_correction()
    original_materialize: Callable[..., Any] = base.v4auth.materialize

    def materialize_with_repair(
        sha: str, paths: list[str], repository: Path
    ) -> None:
        original_materialize(sha, paths, repository)
        if sha == base.v4auth.SOURCE_SHA:
            repaired = repair_materialized_source(repository)
            print(
                "STABLECOIN_V5_EXECUTION_REPAIR",
                json.dumps(
                    {
                        "correction_id": CORRECTION_ID,
                        "path": str(repaired),
                        "old_reference_count": 1,
                        "new_reference_count": 1,
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
