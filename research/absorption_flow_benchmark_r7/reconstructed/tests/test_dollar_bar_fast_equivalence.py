from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "research/dollar_bar_absorption_v2_optimized.py"
S = importlib.util.spec_from_file_location("dbarfasttest", P)
assert S and S.loader
M = importlib.util.module_from_spec(S)
sys.modules[S.name] = M
S.loader.exec_module(M)


def _synthetic_execution_inputs():
    index = pd.date_range("2023-01-01T00:00:00Z", periods=420, freq="1min")
    open_ = np.full(len(index), 100.0)
    close = open_.copy()
    high = np.full(len(index), 100.20)
    low = np.full(len(index), 99.80)

    # Long target, short stop, horizon with funding, and long gap-stop paths.
    high[20] = 104.0
    high[55] = 102.0
    open_[251] = close[251] = 98.0
    high[251] = 98.2
    low[251] = 97.8

    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close}, index=index
    )
    funding = pd.DataFrame(
        {"funding_rate": [0.0001]}, index=pd.DatetimeIndex([index[115]])
    )
    funding.index.name = "timestamp"
    minute = {"BTCUSDT": frame}
    views = {"BTCUSDT": M.make_fast_view(frame)}
    funding_by_symbol = {"BTCUSDT": funding}
    candidate = M.m.DollarCandidate(
        target_bars_per_day=144,
        family="aligned_continuation",
        horizon_bars=6,
        z_min=3.0,
        z_max=np.inf,
        terminal_bars=2,
        flow_threshold=0.10,
        efficiency_min=0.45,
        hold_min=0.70,
        stop_buffer_atr=0.25,
        reward_risk=2.0,
        maximum_holding_minutes=30,
    )
    events = [
        M.base.Event(candidate.candidate_id, "BTCUSDT", index[9], index[10], index[10], 1, 3.0, 1.0, 99.5, 100.2, candidate.family),
        M.base.Event(candidate.candidate_id, "BTCUSDT", index[49], index[50], index[50], -1, 2.5, 1.0, 100.5, 99.8, candidate.family),
        M.base.Event(candidate.candidate_id, "BTCUSDT", index[99], index[100], index[100], 1, 2.0, 1.0, 99.5, 100.2, candidate.family),
        M.base.Event(candidate.candidate_id, "BTCUSDT", index[249], index[250], index[250], 1, 2.0, 1.0, 99.5, 100.2, candidate.family),
    ]
    return candidate, events, minute, views, funding_by_symbol


def test_fast_execution_matches_original_deterministic_paths():
    candidate, events, minute, views, funding = _synthetic_execution_inputs()
    checked = 0
    reasons = set()
    for event in events:
        for cost in M.base.COST_PROFILES:
            for equity in (10_000.0, 12_345.67):
                old = M.base.execute_event(
                    event, candidate, equity, minute, funding, cost, M.base.EngineConfig()
                )
                new = M.execute_event_fast(
                    event, candidate, equity, minute, views, funding, cost, M.base.EngineConfig()
                )
                assert (old is None) == (new is None)
                if old is None:
                    continue
                od = dataclasses.asdict(old)
                nd = dataclasses.asdict(new)
                assert od.keys() == nd.keys()
                for key in od:
                    a, b = od[key], nd[key]
                    if isinstance(a, float):
                        assert np.isclose(a, b, rtol=1e-12, atol=1e-10, equal_nan=True), (key, a, b)
                    else:
                        assert a == b, (key, a, b)
                checked += 1
                reasons.add(old.exit_reason)
    assert checked == len(events) * len(M.base.COST_PROFILES) * 2
    assert {"target", "stop", "horizon", "gap_stop"}.issubset(reasons)
