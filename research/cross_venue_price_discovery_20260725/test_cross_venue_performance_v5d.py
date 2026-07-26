from __future__ import annotations

import numpy as np
import pandas as pd

import cross_venue_execution_v5 as base
import cross_venue_performance_v5d as performance


def test_cached_quote_index_is_exact_and_reused() -> None:
    frame = pd.DataFrame(
        {
            "bn_first_event_us": [np.nan, 1_000_100.0, np.nan, 1_000_300.0, 1_000_400.0],
        },
        index=np.arange(0, 500, 100, dtype=np.int64),
    )

    # Establish the authoritative pre-cache result and target lookups first.
    performance.clear_frame_cache(frame)
    base._first_quote_index = performance._ORIGINAL_FIRST_QUOTE_INDEX
    performance._PATCHED = False
    expected_positions, expected_times = performance._ORIGINAL_FIRST_QUOTE_INDEX(frame)
    targets = (0, 1_000_100, 1_000_250, 1_000_400, 2_000_000)
    expected_lookup = [base._first_quote_after(frame, target) for target in targets]

    performance.patch()
    observed_positions, observed_times = base._first_quote_index(frame)
    observed_lookup = [base._first_quote_after(frame, target) for target in targets]

    np.testing.assert_array_equal(observed_positions, expected_positions)
    np.testing.assert_array_equal(observed_times, expected_times)
    assert observed_lookup == expected_lookup

    again_positions, again_times = base._first_quote_index(frame)
    assert again_positions is observed_positions
    assert again_times is observed_times
    assert not observed_positions.flags.writeable
    assert not observed_times.flags.writeable


def test_cache_is_scoped_to_each_frame() -> None:
    performance.patch()
    left = pd.DataFrame({"bn_first_event_us": [100.0, np.nan]}, index=[0, 100])
    right = pd.DataFrame({"bn_first_event_us": [np.nan, 200.0]}, index=[0, 100])
    left_positions, left_times = base._first_quote_index(left)
    right_positions, right_times = base._first_quote_index(right)
    np.testing.assert_array_equal(left_positions, np.array([0]))
    np.testing.assert_array_equal(left_times, np.array([100], dtype=np.int64))
    np.testing.assert_array_equal(right_positions, np.array([1]))
    np.testing.assert_array_equal(right_times, np.array([200], dtype=np.int64))
