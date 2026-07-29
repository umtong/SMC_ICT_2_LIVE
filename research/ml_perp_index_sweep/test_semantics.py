import pandas as pd

from research.ml_perp_index_sweep.run import attach_paired_levels, route_global_slot


def test_paired_index_level_comes_from_derivative_extreme_bar():
    day1 = pd.Timestamp("2021-01-01", tz="UTC")
    day2 = pd.Timestamp("2021-01-02", tz="UTC")
    frame = pd.DataFrame([
        {"day": day1, "high": 100.0, "low": 90.0, "open": 95.0, "close": 96.0, "idx_high": 98.0, "idx_low": 89.0},
        {"day": day1, "high": 99.0, "low": 91.0, "open": 96.0, "close": 97.0, "idx_high": 105.0, "idx_low": 90.0},
        {"day": day2, "high": 101.0, "low": 95.0, "open": 97.0, "close": 98.0, "idx_high": 99.0, "idx_low": 94.0},
    ])
    paired = attach_paired_levels(frame)
    current = paired[paired["day"] == day2].iloc[0]
    assert current["prev_d_high"] == 100.0
    assert current["prev_high_idx_level"] == 98.0
    assert current["prev_high_idx_level"] != 105.0


def test_global_slot_blocks_overlapping_candidate():
    frame = pd.DataFrame([
        {"entry_time_ms": 1000, "exit_time_ms": 5000, "target_distance": 0.02, "stop_distance": 0.01, "symbol": "BTCUSDT"},
        {"entry_time_ms": 2000, "exit_time_ms": 3000, "target_distance": 0.03, "stop_distance": 0.01, "symbol": "ETHUSDT"},
        {"entry_time_ms": 5000, "exit_time_ms": 7000, "target_distance": 0.02, "stop_distance": 0.01, "symbol": "ETHUSDT"},
    ])
    selected = route_global_slot(frame)
    assert selected["entry_time_ms"].tolist() == [1000, 5000]
