from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import run_stablecoin_profit_v5_single_pass_authority_repaired as prior

ROOT = Path(__file__).resolve().parents[1]
CORRECTION_PATH = (
    ROOT
    / "research"
    / "execution"
    / "stablecoin_profit_v5_20260727"
    / "EXECUTION_CORRECTION_011_ENTRY_TIME_GLOBAL_SLOT_ARBITRATION_BEFORE_OUTCOME.json"
)
SEQUENCE_CORRECTION_ID = (
    "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-"
    "POST-RECONSTRUCT-ENTRY-TIME-ARBITRATION-012"
)
_ORIGINAL_AUTHORITY_RUN_WRAPPER = prior._authority_run_wrapper


def _load_sequence_correction() -> dict[str, Any]:
    payload = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    sequence = payload.get("implementation_sequence_correction")
    if not isinstance(sequence, dict):
        raise AssertionError("post-reconstruct arbitration correction missing")
    if sequence.get("state") != "PRE_OUTCOME_REGRESSION_FAILURE":
        raise AssertionError(sequence.get("state"))
    if sequence.get("source_decision_observed") is not False:
        raise AssertionError("source outcome was observed before sequence correction")
    if sequence.get("market_or_economic_outcome_observed") is not False:
        raise AssertionError("market outcome was observed before sequence correction")
    if sequence.get("required_application_point") != (
        "after reconstruct.py succeeds and before py_compile, scientific tests or market access"
    ):
        raise AssertionError(sequence.get("required_application_point"))
    return sequence


def _economic_repository_after_reconstruct(command: list[str]) -> Path | None:
    for value in command:
        try:
            path = Path(value)
        except (TypeError, ValueError):
            continue
        if (
            path.name == "reconstruct.py"
            and path.parent.name == "ml_stablecoin_issuance_economic_20260726"
        ):
            return path.resolve().parents[2]
    return None


def _post_reconstruct_run_wrapper(
    original_run: Callable[..., Any], work_dir: Path
) -> Callable[..., Any]:
    inherited = _ORIGINAL_AUTHORITY_RUN_WRAPPER(original_run, work_dir)

    def wrapped(
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
        log: Path | None = None,
    ) -> Any:
        repository = _economic_repository_after_reconstruct(command)
        completed = inherited(
            command,
            env=env,
            check=check,
            log=log,
        )
        if repository is not None and int(completed.returncode) == 0:
            repaired = prior.repair_materialized_entry_time_route(repository)
            print(
                "STABLECOIN_V5_POST_RECONSTRUCT_ARBITRATION_APPLIED",
                json.dumps(
                    {
                        "sequence_correction_id": SEQUENCE_CORRECTION_ID,
                        "arbitration_correction_id": prior.ARBITRATION_CORRECTION_ID,
                        "path": str(repaired),
                        "scientific_contract_changed": False,
                        "model_or_payoff_changed": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        return completed

    return wrapped


def main() -> int:
    _load_sequence_correction()
    original_wrapper = prior._authority_run_wrapper
    prior._authority_run_wrapper = _post_reconstruct_run_wrapper
    try:
        return prior.main()
    finally:
        prior._authority_run_wrapper = original_wrapper


if __name__ == "__main__":
    raise SystemExit(main())
