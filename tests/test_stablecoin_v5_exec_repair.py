from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_stablecoin_profit_v5_single_pass_authority_repaired as repaired


def _source_path(repository: Path) -> Path:
    return (
        repository
        / "research"
        / "ml_stablecoin_issuance_20260726"
        / "run_pinned_snapshot_source.py"
    )


def _source_gate_path(repository: Path) -> Path:
    return (
        repository
        / "research"
        / "ml_stablecoin_issuance_20260726"
        / "source_gate_blockscout.py"
    )


def _economic_run_path(repository: Path) -> Path:
    return (
        repository
        / "research"
        / "ml_stablecoin_issuance_economic_20260726"
        / "run.py"
    )


def test_temporary_source_overlay_repairs_namespaces_and_authoritative_gate(
    tmp_path: Path,
) -> None:
    path = _source_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "decoded = authority.base.decode_log(",
                'address = authority.base.CONTRACTS["USDT"]["address"]',
                "topic = authority.base.ISSUE_TOPIC",
                'address2 = authority.base.CONTRACTS["USDT"]["address"]',
                repaired._SOURCE_GATE_CALL_OLD.rstrip("\n"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    observed = repaired.repair_materialized_source(tmp_path)

    assert observed == path
    text = path.read_text(encoding="utf-8")
    assert repaired._SOURCE_OLD not in text
    assert text.count(repaired._SOURCE_NEW) == repaired._EXPECTED_SOURCE_REFERENCES
    assert repaired._SOURCE_GATE_CALL_OLD not in text
    assert text.count(repaired._SOURCE_GATE_CALL_NEW) == 1


def test_temporary_source_overlay_fails_closed_on_unexpected_count(
    tmp_path: Path,
) -> None:
    path = _source_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        (repaired._SOURCE_OLD + "placeholder\n") * 3
        + repaired._SOURCE_GATE_CALL_OLD,
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="expected 4"):
        repaired.repair_materialized_source(tmp_path)


def test_temporary_source_overlay_fails_closed_without_lower_gate_call(
    tmp_path: Path,
) -> None:
    path = _source_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        (repaired._SOURCE_OLD + "placeholder\n") * 4,
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="expected 1"):
        repaired.repair_materialized_source(tmp_path)


def test_schema_binding_correction_is_outcome_sealed() -> None:
    payload = repaired._load_schema_binding_correction()
    assert payload["correction_id"] == repaired.SCHEMA_BINDING_CORRECTION_ID
    assert payload["observed_state"]["source_decision_observed"] is False
    assert payload["observed_state"]["market_archive_opened"] is False
    assert payload["observed_state"]["orders_submitted"] is False


def test_exact_availability_prefetch_overlay_is_execution_only(
    tmp_path: Path,
) -> None:
    path = _source_gate_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        "before\n" + repaired._SOURCE_LOOP_OLD + "after\n",
        encoding="utf-8",
    )

    observed = repaired.repair_materialized_source_prefetch(tmp_path)

    assert observed == path
    text = path.read_text(encoding="utf-8")
    assert repaired._SOURCE_LOOP_OLD not in text
    assert text.count(repaired._SOURCE_LOOP_NEW) == 1
    assert 'for offset in (12, 64)' in text
    assert 'cache.update(post_batch(chunk))' in text
    assert 'client.block_timestamp(block)' in text


def test_strict_fixture_overlay_changes_tests_not_runtime(tmp_path: Path) -> None:
    causal_test = (
        tmp_path
        / "research"
        / "ml_stablecoin_issuance_economic_20260726"
        / "test_run_causal.py"
    )
    strict_guard = (
        tmp_path
        / "sourcefix"
        / "ml_stablecoin_causal_guard_20260726"
        / "strict_guard.py"
    )
    causal_test.parent.mkdir(parents=True)
    strict_guard.parent.mkdir(parents=True)
    causal_test.write_text("before\n" + repaired._TEST_OLD + "after\n", encoding="utf-8")
    strict_guard.write_text("before\n" + repaired._GAP_OLD + "after\n", encoding="utf-8")

    observed_test, observed_guard = repaired.repair_materialized_strict_fixtures(
        tmp_path
    )

    assert observed_test == causal_test
    assert observed_guard == strict_guard
    assert repaired._TEST_NEW in causal_test.read_text(encoding="utf-8")
    assert repaired._GAP_NEW in strict_guard.read_text(encoding="utf-8")
    assert "def strict_build_rows" not in strict_guard.read_text(encoding="utf-8")


def test_entry_time_route_overlay_changes_only_global_competition_clock(
    tmp_path: Path,
) -> None:
    path = _economic_run_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        "before\n" + repaired._ROUTE_OLD + "after\n",
        encoding="utf-8",
    )

    observed = repaired.repair_materialized_entry_time_route(tmp_path)

    assert observed == path
    text = path.read_text(encoding="utf-8")
    assert repaired._ROUTE_OLD not in text
    assert text.count(repaired._ROUTE_NEW) == 1
    assert "executable_ms = candidates[i].entry_ms" in text
    assert "key=lambda t: (t.ev_bps, t.decision_ms, t.symbol, t.event_id)" in text


def test_authority_wrapper_adds_arbitration_test_and_only_validator_is_nonblocking(
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], bool, Path | None]] = []

    def fake_run(
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
        log: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del env
        calls.append((command, check, log))
        return subprocess.CompletedProcess(command, 7)

    wrapped = repaired._authority_run_wrapper(fake_run, tmp_path)

    internal_pytest = [
        sys.executable,
        "-m",
        "pytest",
        "/tmp/frozen/test_run.py",
    ]
    wrapped(internal_pytest, check=True, log=None)
    assert calls[-1][1] is True
    assert str(repaired.ARBITRATION_TEST) in calls[-1][0]

    validator_command = [sys.executable, str(repaired.PROJECT_VALIDATOR)]
    completed = wrapped(validator_command, check=True, log=tmp_path / "validator.log")

    assert completed.returncode == 7
    assert calls[-1][1] is False
    assert (tmp_path / "PROJECT_VALIDATION_EXIT_CODE.txt").read_text() == "7\n"

    ordinary = [sys.executable, "scientific_test.py"]
    wrapped(ordinary, check=True, log=None)
    assert calls[-1][0] == ordinary
    assert calls[-1][1] is True


def test_failure_record_uses_resolved_cli_publish_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publish = tmp_path / "nested" / "publish"
    work = tmp_path / "work"

    def fail(_work: Path, _publish: Path) -> int:
        raise RuntimeError("synthetic carrier failure")

    monkeypatch.setattr(repaired, "execute", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "repair",
            "--work-dir",
            str(work),
            "--publish-dir",
            str(publish),
        ],
    )

    assert repaired.main() == 1
    payload = json.loads((publish / "EXECUTION_FAILURE.json").read_text())
    assert payload["status"] == "EXECUTION_FAILURE_NOT_SCIENTIFIC_RESULT"
    assert payload["error_type"] == "RuntimeError"
    assert (
        payload["exact_availability_batch_prefetch_correction_id"]
        == repaired.PREFETCH_CORRECTION_ID
    )
    assert (
        payload["entry_time_global_slot_arbitration_correction_id"]
        == repaired.ARBITRATION_CORRECTION_ID
    )
    assert (
        payload["authoritative_source_schema_binding_correction_id"]
        == repaired.SCHEMA_BINDING_CORRECTION_ID
    )
    assert payload["official_2024_2026_opened"] is False
    assert payload["orders_submitted"] is False
