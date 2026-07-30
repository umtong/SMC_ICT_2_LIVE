from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run as base
import run_boundary_corrected as corrected


def _candidate() -> base.EventCandidate:
    return base.EventCandidate(
        event_id="boundary-test",
        symbol="BTCUSDT",
        date="2022-12-31",
        side_level="upper",
        action="ACCEPT",
        direction=1,
        level=100.0,
        midpoint=95.0,
        decision_5m_idx=0,
        decision_ms=60_000,
        entry_ms=120_000,
        stop_price=90.0,
        target_price=float("nan"),
        score=1.0,
        penetration_atr=1.0,
        close_depth_atr=1.0,
        excursion_extreme=101.0,
        state_fail_type="CLOSE_INSIDE",
    )


def test_later_year_target_cannot_value_prior_year_position() -> None:
    # Boundary at 5 minutes. The +1.5R target is touched only after the boundary.
    data = {
        "t": np.arange(0, 8 * 60_000, 60_000, dtype=np.int64),
        "open": np.array([100, 100, 100, 101, 102, 103, 115, 115], dtype=float),
        "high": np.array([101, 101, 102, 103, 104, 104, 116, 116], dtype=float),
        "low": np.array([99, 99, 99, 100, 101, 102, 103, 114], dtype=float),
        "close": np.array([100, 100, 101, 102, 103, 103, 115, 115], dtype=float),
        "observed": np.ones(8, dtype=bool),
        "ft": np.array([], dtype=np.int64),
        "fr": np.array([], dtype=float),
        "five_available": np.array([60_000, 360_000], dtype=np.int64),
        "five_close": np.array([101.0, 115.0], dtype=float),
    }
    boundary = 5 * 60_000
    outcome = corrected.simulate_until(_candidate(), data, boundary)
    assert outcome is not None
    assert outcome["exit_reason"] == "MARK_STAGE_BOUNDARY"
    assert outcome["completed"] is False
    assert outcome["forced_boundary_close"] is False
    assert outcome["exit_ms"] == boundary
    assert outcome["exit_price"] == 103.0


def test_state_exit_executable_at_boundary_is_not_backdated() -> None:
    data = {
        "t": np.arange(0, 7 * 60_000, 60_000, dtype=np.int64),
        "open": np.full(7, 100.0),
        "high": np.full(7, 101.0),
        "low": np.full(7, 99.0),
        "close": np.full(7, 100.5),
        "observed": np.ones(7, dtype=bool),
        "ft": np.array([], dtype=np.int64),
        "fr": np.array([], dtype=float),
        # Acceptance fails at decision availability 240k; execution is 300k,
        # exactly the annual boundary and therefore not a pre-boundary exit.
        "five_available": np.array([60_000, 240_000], dtype=np.int64),
        "five_close": np.array([101.0, 99.0], dtype=float),
    }
    boundary = 300_000
    assert corrected.state_exit_ms_until(_candidate(), data, boundary) is None
