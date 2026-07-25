from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "research" / "yt20_alpha_001" / "causal_core.py"
SPEC = importlib.util.spec_from_file_location("yt20_alpha_001_causal_core", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)
Bar = CORE.Bar


def test_touch_never_enters_same_bar() -> None:
    assert CORE.next_event_entry_index(5, 10) == 6
    assert CORE.next_event_entry_index(9, 10) is None


def test_target_requires_strict_trade_through() -> None:
    assert not CORE.target_crossed(1, Bar(99, 100.01, 98, 100), 100, 1)
    assert CORE.target_crossed(1, Bar(99, 100.02, 98, 100), 100, 1)
    assert not CORE.target_crossed(-1, Bar(101, 102, 99.99, 100), 100, 1)
    assert CORE.target_crossed(-1, Bar(101, 102, 99.98, 100), 100, 1)


def test_same_bar_stop_and_target_is_stop() -> None:
    bar = Bar(100, 103, 97, 101)
    assert CORE.conservative_exit(1, bar, 98, 102, 1) == "stop"
    assert CORE.conservative_exit(-1, bar, 102, 98, 1) == "stop"


def test_gap_stop_not_capped() -> None:
    assert CORE.adverse_gap_stop_price(1, 90, 98, 3) < 90
    assert CORE.adverse_gap_stop_price(-1, 110, 102, 3) > 110


def test_global_slot_unique() -> None:
    intervals = [(10, 20), (15, 16), (21, 30), (25, 40), (41, -1), (50, 60)]
    assert CORE.select_non_overlapping(intervals) == [(10, 20), (21, 30), (41, -1)]
