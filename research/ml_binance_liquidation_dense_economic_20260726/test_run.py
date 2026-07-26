from __future__ import annotations

import numpy as np
import pandas as pd

import run


def test_first_passage_tree_respects_query_bounds() -> None:
    tree = run.FirstPassageTree(
        np.array([1.0, 2.0, 5.0, 3.0]),
        np.array([0.9, 0.8, 0.7, 0.4]),
    )
    assert tree.first_ge(0, 4, 4.0) == 2
    assert tree.first_ge(0, 2, 4.0) is None
    assert tree.first_le(0, 4, 0.5) == 3
    assert tree.first_le(0, 3, 0.5) is None


def test_valid_run_end_stops_before_gap() -> None:
    valid = np.array([True, True, False, True, True], dtype=bool)
    ends = run.valid_run_end(valid)
    assert ends.tolist() == [2, 2, 2, 5, 5]


def test_structural_ev_routes_both_directions_and_flat() -> None:
    long_side, _ = run.action_for_row(
        {"p_up": 0.9, "upper_distance": 0.02, "lower_distance": 0.01}, 24
    )
    short_side, _ = run.action_for_row(
        {"p_up": 0.1, "upper_distance": 0.01, "lower_distance": 0.02}, 24
    )
    flat_side, flat_ev = run.action_for_row(
        {"p_up": 0.5, "upper_distance": 0.001, "lower_distance": 0.001}, 24
    )
    assert long_side == 1
    assert short_side == -1
    assert flat_side == 0 and flat_ev < 0


def test_global_slot_blocks_overlapping_signal() -> None:
    candidates, state = run.synthetic_state_and_candidates()
    duplicate = candidates.iloc[[0]].copy()
    duplicate["event_key"] = "same-time-lower-ev"
    duplicate["p_up"] = 0.8
    combined = pd.concat([candidates, duplicate], ignore_index=True)
    replay = run.replay(combined, state, "confirmation", run.PathConfig(12.0))
    assert replay.metrics["trades"] == 2
    assert all(record["event_key"] != "same-time-lower-ev" for record in replay.trade_records)


def test_winner_removal_reroutes_chronologically() -> None:
    candidates, state = run.synthetic_state_and_candidates()
    alternate = candidates.iloc[[0]].copy()
    alternate["event_key"] = "alternate-after-removal"
    alternate["p_up"] = 0.8
    combined = pd.concat([candidates, alternate], ignore_index=True)
    ordinary = run.replay(combined, state, "confirmation", run.PathConfig(12.0))
    removed = run.winner_removal(
        ordinary, combined, state, "confirmation", run.PathConfig(12.0)
    )
    assert "synthetic-0" in removed["top_five_event_keys"]
    assert removed["without_top_five"]["trades"] == 1


def test_trade_has_no_elapsed_time_exit() -> None:
    candidates, _ = run.synthetic_state_and_candidates()
    assert set(candidates["outcome"]) == {"UPPER_FIRST", "LOWER_FIRST"}
    source = open(run.__file__, encoding="utf-8").read().lower()
    assert "maximum_hold" not in source
    assert "time_exit" not in source
    assert "hold_bars" not in source


def test_partition_boundary_is_strictly_pre_2024() -> None:
    assert run.END_EXCLUSIVE == pd.Timestamp("2024-01-01T00:00:00Z")
    assert run.PARTITIONS["development"][1] == run.END_EXCLUSIVE


def test_model_matrix_uses_exact_feature_order() -> None:
    frame = pd.DataFrame([{name: index for index, name in enumerate(run.MODEL_FEATURES)}])
    matrix = run.model_matrix(frame)
    assert matrix.shape == (1, len(run.MODEL_FEATURES))
    assert matrix[0].tolist() == list(range(len(run.MODEL_FEATURES)))
