import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from passive_source_limit_screen import (
    Candidate,
    classify_state,
    make_pools,
    natural_geometry,
    simulate,
)


def micro(rows):
    frame = pd.DataFrame(
        rows,
        columns=[
            "start_time_ms",
            "open",
            "high",
            "low",
            "close",
            "buy_turnover",
            "sell_turnover",
        ],
    )
    frame["available_at_ms"] = frame.start_time_ms + 500
    return frame


def test_accept_state():
    frame = micro([(i * 500, 100, 101, 100, 101, 10, 1) for i in range(10)])
    result = classify_state(frame, 0, 100, 1)
    assert result and result["state"] == "ACCEPT" and result["outside_dwell"] == 1


def test_reject_state():
    rows = []
    for i in range(10):
        close = 101 if i < 3 else 99
        rows.append((i * 500, 100, max(101, close), min(99, close), close, 5, 5))
    result = classify_state(micro(rows), 0, 100, 1)
    assert result and result["state"] == "REJECT"


def test_radius2_pools_are_causal():
    bars = pd.DataFrame(
        {
            "bar_ms": [i * 900_000 for i in range(7)],
            "high": [1, 2, 5, 2, 1, 3, 2],
            "low": [0, -1, -2, -1, 0, -3, 0],
            "available_at_ms": [(i + 1) * 900_000 for i in range(7)],
        }
    )
    pools = make_pools(bars, 0.1)
    high = [pool for pool in pools if pool.side > 0 and pool.swing_time_ms == 2 * 900_000][0]
    assert high.available_at_ms == 5 * 900_000


def test_natural_floor_geometry():
    candidate = Candidate(
        "x",
        "BTCUSDT",
        "w",
        "REJECT",
        -1,
        0,
        5_000,
        5_500,
        "s",
        100,
        "t",
        90,
        102,
        102,
        0,
        0,
        0,
    )
    geometry = natural_geometry(candidate, 12)
    assert geometry and geometry[0] > 0.5


def test_one_tick_penetration_required():
    candidate = Candidate(
        "x",
        "BTCUSDT",
        "w",
        "ACCEPT",
        1,
        0,
        5_000,
        5_500,
        "s",
        100,
        "t",
        110,
        98,
        101,
        1,
        1,
        1,
    )
    frame = micro(
        [
            (6_000, 101, 105, 99.95, 104, 1, 1),
            (6_500, 104, 111, 103, 110, 1, 1),
        ]
    )
    result = simulate(candidate, frame, 7_000, 12)
    assert result["outcome"].startswith("UNFILLED")
