from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
RUNNER_TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
WORK = RUNNER_TEMP / "stablecoin_strict_v3_validation_hook"
MARKER = WORK / "SUMMARY.json"
SOURCE_SHA = "73aac90eacdc0ddcc34f4e45f0ff8d9369e5b539"
STRICT_SHA = "209a0fbe6e2f61d2c58b3eb7910b8c0c139cd46c"
SOURCE_ROOT = ROOT / "research/ml_stablecoin_issuance_20260726"
ECON_ROOT = ROOT / "research/ml_stablecoin_issuance_economic_20260726"
GUARD_ROOT = ROOT / "sourcefix/ml_stablecoin_causal_guard_20260726"
SOURCE_OUT = WORK / "source"
ECON_OUT = WORK / "economic"
MARKET_CACHE = WORK / "market"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def emit(payload: dict) -> None:
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    MARKER.write_text(encoded + "\n", encoding="utf-8")
    print("STABLECOIN_STRICT_V3_RESULT_BEGIN", flush=True)
    print(encoded, flush=True)
    print("STABLECOIN_STRICT_V3_RESULT_END", flush=True)


def run(command: list[str], *, env: dict[str, str] | None = None, allowed: Iterable[int] = (0,)) -> int:
    print("STABLECOIN_STRICT_V3_COMMAND", json.dumps(command), flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=env, text=True)
    if completed.returncode not in set(int(value) for value in allowed):
        raise RuntimeError(f"command failed rc={completed.returncode}: {command}")
    return int(completed.returncode)


def run_logged(
    command: list[str],
    log_path: Path,
    *,
    env: dict[str, str],
    allowed: Iterable[int] = (0,),
) -> int:
    print("STABLECOIN_STRICT_V3_COMMAND", json.dumps(command), flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = completed.stdout or ""
    log_path.write_text(output, encoding="utf-8")
    print(output, end="" if output.endswith("\n") else "\n", flush=True)
    if completed.returncode not in set(int(value) for value in allowed):
        raise RuntimeError(f"command failed rc={completed.returncode}: {command}")
    return int(completed.returncode)


def materialize(commit: str, paths: list[str]) -> None:
    run(["git", "fetch", "--no-tags", "--depth=1", "origin", commit])
    observed = subprocess.check_output(["git", "rev-parse", "FETCH_HEAD"], cwd=ROOT, text=True).strip()
    if observed != commit:
        raise RuntimeError(f"fetched {observed}, expected {commit}")
    for relative in paths:
        shutil.rmtree(ROOT / relative, ignore_errors=True)
    quoted = " ".join(paths)
    run(["bash", "-lc", f"set -euo pipefail; git archive {commit} {quoted} | tar -x"])


def assert_source_result(root: Path) -> tuple[dict, bool]:
    result = json.loads((root / "SOURCE_GATE_RESULT.json").read_text(encoding="utf-8"))
    assert result["claim_id"] == "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
    assert result["status"] in {
        "PASS",
        "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE",
        "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE",
    }
    for key in (
        "market_outcome_opened",
        "model_fit",
        "trade_or_pnl_opened",
        "official_2024_2026_opened",
        "orders_submitted",
    ):
        assert result[key] is False
    authorized = result["status"] == "PASS"
    if authorized:
        manifest = json.loads((root / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
        events = root / "EVENTS.jsonl"
        rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert result["source_schema_id"] == "STABLECOIN_SUPPLY_USDT_ISSUE_REDEEM_USDC_ZERO_TRANSFER_V1"
        assert result["source_correction_id"] == "CORRECTION-20260726-ML-STABLECOIN-USDT-ISSUE-REDEEM-010"
        assert result["pass_checks"] and all(result["pass_checks"].values())
        assert result["event_semantics"]["ordinary_usdt_transfer_excluded"] is True
        assert int(result["event_count"]) >= 120
        assert len(result["months_with_events"]) >= 24
        assert sorted(result["distinct_tokens"]) == ["USDC", "USDT"]
        assert {row["token"] for row in rows} == {"USDC", "USDT"}
        assert {row["direction"] for row in rows}.issubset({"MINT", "BURN"})
        assert all(int(row["available_timestamp_12"]) < 1704067200 for row in rows)
        assert all(int(row["available_timestamp_64"]) < 1704067200 for row in rows)
        assert sha256_file(events) == manifest["events_sha256"]
    return result, authorized


def assert_economic_result(root: Path) -> tuple[dict, dict]:
    result_path = root / "RESULT.json"
    full_path = root / "FULL_RESULT.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    full = json.loads(full_path.read_text(encoding="utf-8"))
    assert result["claim_id"] == "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
    assert result["engine"] == "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_STRICT_CAUSAL_V3"
    assert result["status"] in {
        "PRE2024_BELOW_GATE",
        "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1",
    }
    assert result["orders_submitted"] is False
    assert result["official_2024h1_opened"] is False
    assert result["official_2024_2026_opened"] is False
    guard = result["strict_causal_guard"]
    assert guard["correction_id"] == "CORRECTION-20260727-ML-STABLECOIN-PREENTRY-INFORMATION-BOUNDARY-002"
    assert guard["source_decision_second_respected"] is True
    assert guard["latest_completed_bar_cutoff_enforced"] is True
    assert guard["decision_reference_price_pre_entry"] is True
    assert guard["future_entry_open_used_for_model_or_action"] is False
    assert guard["entry_open_used_for_realized_execution_only"] is True
    assert guard["stage_boundary_positions_marked_not_closed"] is True
    assert guard["fatal_validity_violation"] is False
    serialized = json.dumps(full, sort_keys=True)
    assert '"exit_reason": "SOURCE_BOUNDARY"' not in serialized

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if "forced_boundary_close" in value:
                assert value["forced_boundary_close"] is False
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(full)
    if result["status"] == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1":
        assert result["development_gate"]["all"] is True
        selected = result["risk_search"]["selected"]
        assert selected is not None
        assert selected["growth"] > 0
        assert selected["liquidation"] is False
    return result, full


def main() -> int:
    if MARKER.exists():
        print("STABLECOIN_STRICT_V3_RESULT_BEGIN", flush=True)
        print(MARKER.read_text(encoding="utf-8").strip(), flush=True)
        print("STABLECOIN_STRICT_V3_RESULT_END", flush=True)
        return 0

    WORK.mkdir(parents=True, exist_ok=True)
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "requests==2.32.4",
            "pytest==8.3.5",
            "numpy==2.1.3",
            "pandas==2.2.3",
            "scikit-learn==1.6.1",
            "pyarrow==18.1.0",
        ]
    )
    materialize(SOURCE_SHA, ["research/ml_stablecoin_issuance_20260726"])
    materialize(
        STRICT_SHA,
        [
            "research/ml_stablecoin_issuance_economic_20260726",
            "sourcefix/ml_stablecoin_causal_guard_20260726",
        ],
    )

    source_env = os.environ.copy()
    source_env["PYTHONPATH"] = str(SOURCE_ROOT)
    economic_env = os.environ.copy()
    economic_env["PYTHONPATH"] = os.pathsep.join((str(ECON_ROOT), str(GUARD_ROOT)))

    run([sys.executable, str(ECON_ROOT / "reconstruct.py")])
    run([sys.executable, "-m", "py_compile", str(SOURCE_ROOT / "run_pinned_snapshot_source.py")])
    run([sys.executable, "-m", "pytest", "-q", str(SOURCE_ROOT / "test_source_gate.py")], env=source_env)
    run([sys.executable, str(SOURCE_ROOT / "run_pinned_snapshot_source.py"), "--self-test"], env=source_env)
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(ECON_ROOT / "test_run.py"),
            str(ECON_ROOT / "test_run_causal.py"),
            str(GUARD_ROOT / "test_causal_guard.py"),
        ],
        env=economic_env,
    )
    run([sys.executable, str(GUARD_ROOT / "strict_guard.py"), "self-test"], env=economic_env)

    shutil.rmtree(SOURCE_OUT, ignore_errors=True)
    SOURCE_OUT.mkdir(parents=True, exist_ok=True)
    source_rc = run_logged(
        [sys.executable, str(SOURCE_ROOT / "run_pinned_snapshot_source.py"), "--output", str(SOURCE_OUT)],
        SOURCE_OUT / "RUN.log",
        env=source_env,
        allowed=(0, 2),
    )
    (SOURCE_OUT / "RUN_EXIT_CODE.txt").write_text(f"{source_rc}\n", encoding="utf-8")
    if not (SOURCE_OUT / "SOURCE_GATE_RESULT.json").exists():
        run(
            [
                sys.executable,
                str(SOURCE_ROOT / "write_transport_failure.py"),
                "--output",
                str(SOURCE_OUT),
                "--transport",
                "TRANSPORT-20260727-ML-STABLECOIN-STRICT-V3-VALIDATOR-HOOK",
                "--exit-code",
                str(source_rc),
            ],
            env=source_env,
        )
    source_result, authorized = assert_source_result(SOURCE_OUT)
    if not authorized:
        emit(
            {
                "schema_version": 1,
                "claim_id": source_result["claim_id"],
                "source_sha": SOURCE_SHA,
                "strict_sha": STRICT_SHA,
                "source_status": source_result["status"],
                "source_event_count": source_result.get("event_count"),
                "source_month_count": len(source_result.get("months_with_events", [])),
                "source_tokens": source_result.get("distinct_tokens"),
                "economic_status": "NOT_OPENED",
                "next_stage": "CLOSE_SOURCE_OR_REPAIR_TRANSPORT_ONLY",
                "market_outcome_opened": False,
                "orders_submitted": False,
                "source_result_sha256": sha256_file(SOURCE_OUT / "SOURCE_GATE_RESULT.json"),
            }
        )
        return 0

    shutil.rmtree(ECON_OUT, ignore_errors=True)
    ECON_OUT.mkdir(parents=True, exist_ok=True)
    MARKET_CACHE.mkdir(parents=True, exist_ok=True)
    economic_rc = run_logged(
        [
            sys.executable,
            str(GUARD_ROOT / "strict_guard.py"),
            "run",
            "--events",
            str(SOURCE_OUT / "EVENTS.jsonl"),
            "--market-cache",
            str(MARKET_CACHE),
            "--output",
            str(ECON_OUT),
        ],
        ECON_OUT / "RUN.log",
        env=economic_env,
        allowed=(0, 2),
    )
    (ECON_OUT / "RUN_EXIT_CODE.txt").write_text(f"{economic_rc}\n", encoding="utf-8")
    result, _ = assert_economic_result(ECON_OUT)
    next_stage = "CHANGE_ALPHA"
    if result["status"] == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1":
        next_stage = "OFFICIAL_2024H1_IMMEDIATELY"
    emit(
        {
            "schema_version": 1,
            "claim_id": result["claim_id"],
            "source_sha": SOURCE_SHA,
            "strict_sha": STRICT_SHA,
            "source_status": source_result["status"],
            "source_event_count": source_result.get("event_count"),
            "source_month_count": len(source_result.get("months_with_events", [])),
            "source_tokens": source_result.get("distinct_tokens"),
            "economic_status": result["status"],
            "engine": result["engine"],
            "strict_causal_guard": result["strict_causal_guard"],
            "confirmation_gate": result.get("confirmation_gate"),
            "development_gate": result.get("development_gate"),
            "risk_search": result.get("risk_search"),
            "next_stage": next_stage,
            "orders_submitted": result["orders_submitted"],
            "official_2024h1_opened": result["official_2024h1_opened"],
            "source_result_sha256": sha256_file(SOURCE_OUT / "SOURCE_GATE_RESULT.json"),
            "events_sha256": sha256_file(SOURCE_OUT / "EVENTS.jsonl"),
            "economic_result_sha256": sha256_file(ECON_OUT / "RESULT.json"),
            "economic_full_result_sha256": sha256_file(ECON_OUT / "FULL_RESULT.json"),
            "result": result,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
