from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_PATH = Path(__file__).with_name("run.py")
spec = importlib.util.spec_from_file_location("ml_xvenue_l2_sweep_run", MODULE_PATH)
assert spec and spec.loader
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def test_sealed_dates() -> None:
    run.assert_allowed_date("2023-12-31")
    try:
        run.assert_allowed_date("2024-01-01")
    except run.ResearchError:
        return
    raise AssertionError("2024 seal did not fire")


def test_quote_after_respects_latency_and_freshness() -> None:
    ts = np.array([1_000_000, 1_200_000, 2_500_000], dtype=np.int64)
    bid = np.array([99.0, 99.5, 100.0])
    ask = np.array([100.0, 100.5, 101.0])
    amount = np.ones(3)
    quote = run.quote_after(ts, bid, ask, amount, amount, 1_100_000)
    assert quote is not None and quote[0] == 1_200_000
    assert run.quote_after(ts, bid, ask, amount, amount, 3_600_001) is None


def test_first_passage_is_timestamp_adverse_on_double_hit() -> None:
    ts = np.array([1_000_000, 2_000_000, 2_000_000], dtype=np.int64)
    px = np.array([100.0, 102.0, 98.0])
    hit = run.first_passage(ts, px, 1_500_000, upper=101.0, lower=99.0)
    assert hit is not None and hit[1] == -1


def test_cost_monotonicity_and_global_slot() -> None:
    frame = pd.DataFrame(
        [
            {
                "event_id": "a",
                "date": "2022-09-01",
                "route": "continuation",
                "entry_time_us": 1_000_000,
                "exit_time_us": 3_000_000,
                "probability": 0.9,
                "cont_realized_gross": 0.01,
                "rev_realized_gross": -0.01,
                "cont_entry": 100.0,
                "rev_entry": 100.0,
                "cont_stop": 99.0,
                "rev_stop": 101.0,
                "prior_60s_turnover": 10_000_000.0,
                "unresolved": False,
            },
            {
                "event_id": "b",
                "date": "2022-09-01",
                "route": "continuation",
                "entry_time_us": 2_000_000,
                "exit_time_us": 4_000_000,
                "probability": 0.9,
                "cont_realized_gross": 0.01,
                "rev_realized_gross": -0.01,
                "cont_entry": 100.0,
                "rev_entry": 100.0,
                "cont_stop": 99.0,
                "rev_stop": 101.0,
                "prior_60s_turnover": 10_000_000.0,
                "unresolved": False,
            },
        ]
    )
    m12, l12 = run.replay_account(frame, 12)
    m24, l24 = run.replay_account(frame, 24)
    assert len(l12) == len(l24) == 1
    assert m12["total_return"] > m24["total_return"]


def test_ev_router_can_stay_flat() -> None:
    frame = pd.DataFrame(
        {
            **{name: [0.0] for name in run.FEATURES},
            "continuation_label": [1],
            "cont_reward": [0.003],
            "cont_loss": [0.003],
            "rev_reward": [0.003],
            "rev_loss": [0.003],
        }
    )

    class DummyModel:
        def predict_proba(self, x: np.ndarray) -> np.ndarray:
            return np.c_[np.full(len(x), 0.5), np.full(len(x), 0.5)]

    class DummyCal:
        def transform(self, x: np.ndarray) -> np.ndarray:
            return x

    scored = run.score_events(DummyModel(), DummyCal(), frame)
    assert scored.iloc[0]["route"] == "flat"


def test_winner_removal_releases_slot() -> None:
    frame = pd.DataFrame(
        [
            {
                "event_id": "winner",
                "date": "2022-09-01",
                "route": "continuation",
                "entry_time_us": 1_000_000,
                "exit_time_us": 4_000_000,
                "probability": 0.9,
                "cont_realized_gross": 0.03,
                "rev_realized_gross": -0.01,
                "cont_entry": 100.0,
                "rev_entry": 100.0,
                "cont_stop": 99.0,
                "rev_stop": 101.0,
                "prior_60s_turnover": 10_000_000.0,
                "unresolved": False,
            },
            {
                "event_id": "rerouted",
                "date": "2022-09-01",
                "route": "continuation",
                "entry_time_us": 2_000_000,
                "exit_time_us": 3_000_000,
                "probability": 0.9,
                "cont_realized_gross": -0.005,
                "rev_realized_gross": 0.005,
                "cont_entry": 100.0,
                "rev_entry": 100.0,
                "cont_stop": 99.0,
                "rev_stop": 101.0,
                "prior_60s_turnover": 10_000_000.0,
                "unresolved": False,
            },
        ]
    )
    _, full = run.replay_account(frame, 12)
    metrics, removed, excluded = run.winner_removed_replay(frame, full, 12)
    assert excluded == ["winner"]
    assert list(removed["event_id"]) == ["rerouted"]
    assert metrics["trades"] == 1
