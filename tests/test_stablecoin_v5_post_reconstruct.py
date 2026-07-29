from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_stablecoin_profit_v5_post_reconstruct_authority as overlay


def _economic_paths(repository: Path) -> tuple[Path, Path]:
    root = (
        repository
        / "research"
        / "ml_stablecoin_issuance_economic_20260726"
    )
    return root / "reconstruct.py", root / "run.py"


def test_entry_time_route_is_applied_after_reconstruct_success(tmp_path: Path) -> None:
    reconstruct, run_path = _economic_paths(tmp_path)
    reconstruct.parent.mkdir(parents=True)
    reconstruct.write_text("# frozen reconstruct fixture\n", encoding="utf-8")
    run_path.write_text(
        "before\n" + overlay.prior._ROUTE_OLD + "after\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
        log: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del env, check, log
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    wrapped = overlay._post_reconstruct_run_wrapper(fake_run, tmp_path / "work")
    completed = wrapped([sys.executable, str(reconstruct)])

    assert completed.returncode == 0
    assert calls == [[sys.executable, str(reconstruct)]]
    text = run_path.read_text(encoding="utf-8")
    assert overlay.prior._ROUTE_OLD not in text
    assert text.count(overlay.prior._ROUTE_NEW) == 1


def test_non_reconstruct_command_does_not_touch_route(tmp_path: Path) -> None:
    _, run_path = _economic_paths(tmp_path)
    run_path.parent.mkdir(parents=True)
    original = "unchanged runtime\n"
    run_path.write_text(original, encoding="utf-8")

    def fake_run(
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
        log: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del env, check, log
        return subprocess.CompletedProcess(command, 0)

    wrapped = overlay._post_reconstruct_run_wrapper(fake_run, tmp_path / "work")
    wrapped([sys.executable, "ordinary_test.py"])

    assert run_path.read_text(encoding="utf-8") == original
