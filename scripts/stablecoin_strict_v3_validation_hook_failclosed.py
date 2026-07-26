from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import stablecoin_strict_v3_validation_hook as base

CANONICAL_SOURCE_SHA = "3631cf01a2a2b91d690b81160e14ba033a298f75"
TRANSPORT_CORRECTION = (
    base.ROOT
    / "research"
    / "execution"
    / "stablecoin_strict_validator_hook_20260727"
    / "EXECUTION_CORRECTION_002_TRANSPORT_EXCEPTION_FAIL_CLOSED.json"
)
SOURCE_AUTHORITY_CORRECTION = (
    base.ROOT
    / "research"
    / "execution"
    / "stablecoin_strict_validator_hook_20260727"
    / "EXECUTION_CORRECTION_003_CANONICAL_SOURCE3631_BEFORE_OUTCOME.json"
)


def _load_correction(path: Path, expected: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("correction_id") != expected:
        raise AssertionError(f"correction identity changed: {path}")
    if payload.get("recorded_before_source_decision") is not True:
        raise AssertionError("correction was not frozen before source decision")
    if payload.get("recorded_before_market_outcome") is not True:
        raise AssertionError("correction was not frozen before market outcome")
    return payload


def _load_corrections() -> tuple[dict[str, Any], dict[str, Any]]:
    transport = _load_correction(
        TRANSPORT_CORRECTION,
        "EXECUTION-CORRECTION-20260727-ML-STABLECOIN-VALIDATOR-TRANSPORT-FAIL-CLOSED-002",
    )
    source = _load_correction(
        SOURCE_AUTHORITY_CORRECTION,
        "EXECUTION-CORRECTION-20260727-ML-STABLECOIN-VALIDATOR-CANONICAL-SOURCE3631-003",
    )
    if source.get("source_sha") != CANONICAL_SOURCE_SHA:
        raise AssertionError("canonical source SHA changed")
    if source.get("strict_sha") != base.STRICT_SHA:
        raise AssertionError("strict economic SHA changed")
    return transport, source


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
    _load_corrections()
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
    base.SOURCE_SHA = CANONICAL_SOURCE_SHA
    base.run = _run_failclosed
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
