from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_stablecoin_profit_v5_transport_window_authority as transport


def test_transport_correction_is_bound_to_recorded_source_failure() -> None:
    payload = transport._load_correction()
    assert payload["correction_id"] == transport.CORRECTION_ID
    assert payload["observed_run"]["workflow_run"] == 30485219744
    assert payload["observed_run"]["source_pass_fail_observed"] is False
    assert payload["observed_run"]["market_archive_opened"] is False
    assert payload["observed_run"]["orders_submitted"] is False


def test_fixed_log_window_overlay_is_exact_and_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "source_gate_blockscout.py"
    path.write_text(
        "before\n" + transport._LOG_QUERY_OLD + "after\n",
        encoding="utf-8",
    )

    observed = transport.apply_fixed_log_windows(path)

    assert observed == path
    text = path.read_text(encoding="utf-8")
    assert transport._LOG_QUERY_OLD not in text
    assert text.count(transport._LOG_QUERY_NEW) == 1
    assert "window_start + 19_999" in text
    assert "window_start = window_end + 1" in text
    assert 'spec["address"]' in text
    assert "direction" in text
    assert "chunks" in text

    with pytest.raises(RuntimeError, match="expected 1"):
        transport.apply_fixed_log_windows(path)


def test_partition_formula_has_no_gap_or_overlap() -> None:
    start = 15_000_123
    end = 15_087_654
    windows: list[tuple[int, int]] = []
    cursor = start
    while cursor <= end:
        stop = min(end, cursor + transport.MAX_LOG_WINDOW_BLOCKS - 1)
        windows.append((cursor, stop))
        cursor = stop + 1

    assert windows[0][0] == start
    assert windows[-1][1] == end
    assert all(
        right_start == left_end + 1
        for (_, left_end), (right_start, _) in zip(windows, windows[1:])
    )
    assert all(
        stop - begin + 1 <= transport.MAX_LOG_WINDOW_BLOCKS
        for begin, stop in windows
    )
