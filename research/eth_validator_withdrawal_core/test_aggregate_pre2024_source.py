from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("aggregate_pre2024_source.py")
SPEC = importlib.util.spec_from_file_location("aggregate_pre2024_source", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["aggregate_pre2024_source"] = MODULE
SPEC.loader.exec_module(MODULE)


def test_validate_index_set_canonicalizes_physical_order() -> None:
    assert MODULE.validate_index_set([3, 1, 2]) == (1, 3)


def test_validate_index_set_rejects_duplicate_and_gap() -> None:
    for values in ([1, 1], [1, 3]):
        try:
            MODULE.validate_index_set(list(values))
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected failure for {values}")


def test_global_daily_continuity_uses_protocol_index() -> None:
    original_start, original_end = MODULE.START, MODULE.END
    MODULE.START = date(2023, 4, 12)
    MODULE.END = date(2023, 4, 13)
    try:
        MODULE.assert_global_continuity(
            [
                {
                    "day": "2023-04-12",
                    "min_withdrawal_index": 0,
                    "max_withdrawal_index": 10,
                },
                {
                    "day": "2023-04-13",
                    "min_withdrawal_index": 11,
                    "max_withdrawal_index": 20,
                },
            ]
        )
    finally:
        MODULE.START, MODULE.END = original_start, original_end


def test_hourly_continuity_is_strict() -> None:
    first = datetime(2023, 4, 12, 22, tzinfo=timezone.utc)
    MODULE.assert_hourly_continuity(
        [
            {"source_hour_start": first},
            {"source_hour_start": first + timedelta(hours=1)},
        ]
    )
    try:
        MODULE.assert_hourly_continuity(
            [
                {"source_hour_start": first},
                {"source_hour_start": first + timedelta(hours=2)},
            ]
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected hourly source-gap failure")


def test_source_confirmation_delay_is_three_minutes() -> None:
    assert MODULE.SOURCE_CONFIRMATION_DELAY == timedelta(minutes=3)
