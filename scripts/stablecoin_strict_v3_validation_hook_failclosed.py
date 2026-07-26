from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import stablecoin_strict_v3_validation_hook as base

CORRECTION = (
    base.ROOT
    / "research"
    / "execution"
    / "stablecoin_strict_validator_hook_20260727"
    / "EXECUTION_CORRECTION_002_TRANSPORT_EXCEPTION_FAIL_CLOSED.json"
)


def _load_correction() -> dict[str, Any]:
    payload = json.loads(CORRECTION.read_text(encoding="utf-8"))
    expected = (
        "EXECUTION-CORRECTION-20260727-ML-STABLECOIN-"
        "VALIDATOR-TRANSPORT-FAIL-CLOSED-002"
    )
    if payload.get("correction_id") != expected:
        raise AssertionError("transport fail-closed correction identity changed")
    if payload.get("recorded_before_source_decision") is not True:
        raise AssertionError("correction was not frozen before source decision")
    if payload.get("recorded_before_market_outcome") is not True:
        raise AssertionError("correction was not frozen before market outcome")
    return payload


_original_run = base.run


def _run_failclosed(
    command: list[str],
    *,
    cwd: Path = base.ROOT,
    env: dict[str, str] | None = None,
    allowed: tuple[int, ...] = (0,),
) -> int:
    is_source_execution = (
        any(str(value).endswith("run_pinned_snapshot_source.py") for value in command)
        and "--output" in command
    )
    effective_allowed = allowed
    if is_source_execution and 1 not in effective_allowed:
        effective_allowed = tuple((*effective_allowed, 1))
    return _original_run(
        command,
        cwd=cwd,
        env=env,
        allowed=effective_allowed,
    )


def self_test() -> None:
    _load_correction()
    observed: list[tuple[tuple[str, ...], tuple[int, ...]]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path = base.ROOT,
        env: dict[str, str] | None = None,
        allowed: tuple[int, ...] = (0,),
    ) -> int:
        del cwd, env
        observed.append((tuple(command), allowed))
        return 0

    global _original_run
    saved = _original_run
    try:
        _original_run = fake_run
        _run_failclosed(
            ["python", "run_pinned_snapshot_source.py", "--output", "/tmp/out"],
            allowed=(0, 2),
        )
        assert observed[-1][1] == (0, 2, 1)
        _run_failclosed(
            ["python", "run_pinned_snapshot_source.py", "--self-test"],
            allowed=(0,),
        )
        assert observed[-1][1] == (0,)
        _run_failclosed(["python", "other.py"], allowed=(0, 2))
        assert observed[-1][1] == (0, 2)
    finally:
        _original_run = saved



def main() -> int:
    self_test()
    base.run = _run_failclosed
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
