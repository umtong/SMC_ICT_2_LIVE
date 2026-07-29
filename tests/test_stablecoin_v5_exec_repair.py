from __future__ import annotations

import json
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


def test_temporary_source_overlay_repairs_all_four_self_test_references(
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
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    observed = repaired.repair_materialized_source(tmp_path)

    assert observed == path
    text = path.read_text(encoding="utf-8")
    assert repaired._OLD_SELF_TEST not in text
    assert (
        text.count(repaired._NEW_SELF_TEST)
        == repaired._EXPECTED_SELF_TEST_REFERENCES
    )


def test_temporary_source_overlay_fails_closed_on_unexpected_count(
    tmp_path: Path,
) -> None:
    path = _source_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        (repaired._OLD_SELF_TEST + "placeholder\n") * 3,
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="exactly four"):
        repaired.repair_materialized_source(tmp_path)


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
    assert payload["official_2024_2026_opened"] is False
    assert payload["orders_submitted"] is False
