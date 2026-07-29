from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).parents[1] / "research" / "ml_lvn_corridor" / "run.py"
SPEC = importlib.util.spec_from_file_location("ml_lvn_corridor_run", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


class FakeCache:
    def __init__(self, frames: dict[tuple[str, str], pd.DataFrame]):
        self.frames = frames
        self.passage_trees = {}

    def get(self, symbol: str, name: str) -> pd.DataFrame:
        return self.frames[(symbol, name)]


def test_first_passage_marks_same_bar_two_boundary_touch_ambiguous() -> None:
    bars = pd.DataFrame({"start_time_ms": [0, 60_000, 120_000], "open": [100.0, 100.0, 100.0], "high": [101.0, 111.0, 102.0], "low": [99.0, 89.0, 98.0]})
    cache = FakeCache({})
    max_tree, min_tree, size, n = MOD.get_passage_tree(cache, "TEST", bars)
    up, down, ambiguous = MOD.first_passage_tree(max_tree, min_tree, size, n, np.array([1], dtype=np.int64), np.array([110.0]), np.array([90.0]))
    assert int(up[0]) == 1
    assert int(down[0]) == 1
    assert int(ambiguous[0]) == 1


def test_fixed_500ms_latency_uses_first_later_minute_open() -> None:
    bars = pd.DataFrame({"start_time_ms": [0, 60_000, 120_000, 180_000], "open": [100.0, 101.0, 102.0, 103.0], "high": [100.5, 101.5, 110.0, 104.0], "low": [99.5, 100.5, 101.0, 96.0]})
    funding = pd.DataFrame({"timestamp_ms": [0], "funding_rate": [0.0]})
    cache = FakeCache({("TEST", "bars_1m"): bars, ("TEST", "funding_events"): funding})
    event = pd.DataFrame({"decision_ms": [60_000], "lower": [97.0], "upper": [109.0]})
    labelled = MOD.label_events(cache, "TEST", event)
    assert int(labelled.loc[0, "activation_ms"]) == 60_500
    assert int(labelled.loc[0, "entry_ms"]) == 120_000
    assert float(labelled.loc[0, "entry_price"]) == 102.0


def test_funding_sign_is_adverse_to_long_and_beneficial_to_short() -> None:
    base = pd.DataFrame({"upper_first": [1.0], "direction": [1], "upper": [110.0], "lower": [90.0], "entry_price": [100.0], "funding_sum": [0.01], "ambiguous": [False]})
    out = MOD.action_returns(base, cost=0.0)
    assert np.isclose(float(out.loc[0, "continuation_return"]), 0.09)
    assert np.isclose(float(out.loc[0, "reversal_return"]), -0.09)


def test_global_slot_selects_highest_edge_and_rejects_overlap() -> None:
    events = pd.DataFrame({
        "resolved": [True, True, True], "entry_ms": [1_000, 1_000, 1_500], "exit_ms": [2_000, 1_200, 1_600],
        "best_ev": [0.5, 0.2, 0.9], "best_action": ["continuation", "continuation", "continuation"],
        "symbol": ["BTCUSDT", "ETHUSDT", "ETHUSDT"], "entry_price": [100.0, 100.0, 100.0],
        "continuation_side": [1, 1, 1], "reversal_side": [-1, -1, -1],
        "continuation_stop": [99.0, 99.0, 99.0], "reversal_stop": [101.0, 101.0, 101.0],
        "continuation_return": [0.02, 0.03, 0.05], "reversal_return": [-0.02, -0.03, -0.05],
        "continuation_exit": [102.0, 103.0, 105.0], "reversal_exit": [98.0, 97.0, 95.0],
        "duration_hours": [1.0, 1.0, 1.0], "ambiguous": [False, False, False],
    })
    sim = MOD.simulate_closed(events, threshold=0.0, risk=0.005, leverage=3.0, cost=0.0)
    assert sim["trades"] == 1
    assert sim["ledger"].iloc[0]["symbol"] == "BTCUSDT"
