from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import run as r


def minute_frame(days: int = 9, turnover: float = 1.0) -> pd.DataFrame:
    n = days * 1440
    t = np.arange(n, dtype=np.int64) * r.MIN_MS
    px = 100.0 + np.sin(np.arange(n) / 100.0)
    return pd.DataFrame(
        dict(
            start_time_ms=t,
            available_at_ms=t + r.MIN_MS,
            observed=True,
            mark_observed=True,
            open=px,
            high=px + 0.1,
            low=px - 0.1,
            close=px,
            volume=1.0,
            turnover=float(turnover),
            mark_open=px,
            symbol="X",
        )
    )


def test_packet_boundaries_no_cross_day_no_minute_reuse_and_frozen_target():
    x = minute_frame(days=9)
    p = r.build_packets(x, "X")
    assert not p.empty
    assert (p.start_ms // r.DAY_MS == p.available_at_ms.sub(1) // r.DAY_MS).all()
    intervals = p[["start_idx", "end_idx"]].sort_values("start_idx").to_numpy()
    assert np.all(intervals[1:, 0] > intervals[:-1, 1])
    assert np.allclose(p.target_turnover, 60.0)
    assert (p.duration_minutes == 60).all()


def test_shifted_packet_features_do_not_use_current_packet():
    x = minute_frame(days=10)
    p = r.build_packets(x, "X")
    assert p.intensity_z.dropna().empty
    assert p.atr20.iloc[:20].isna().all()


def test_entry_clock_is_strictly_after_decision_plus_500ms():
    starts = np.array([0, 60_000, 120_000, 180_000], dtype=np.int64)
    decision = 60_000
    entry_idx = int(np.searchsorted(starts, decision + 500, side="right"))
    assert starts[entry_idx] == 120_000
    assert starts[entry_idx] > decision + 500


def test_funding_sign_and_interval_are_causal():
    f = pd.DataFrame(
        {
            "timestamp_ms": [1000, 2000, 3000],
            "cum_coeff": [1.0, 3.0, 6.0],
        }
    )
    assert r.funding_per_unit(f, None, 1, 1000, 3000) == -5.0
    assert r.funding_per_unit(f, None, -1, 1000, 3000) == 5.0
    assert r.funding_per_unit(f, None, 1, 3000, 3000) == 0.0


def synthetic_event(key: str, entry_ms: int, exit_ms: int, outcome: float, reason: str = "target") -> r.Event:
    side = 1
    entry = 100.0
    return r.Event(
        event_key=key,
        symbol="BTCUSDT",
        side=side,
        packet_idx=0,
        decision_ms=entry_ms - 60_000,
        entry_idx=0,
        entry_ms=entry_ms,
        entry=entry,
        stop=99.0,
        target=101.5,
        boundary=100.0,
        atr=0.5,
        intensity_z=3.0,
        displacement_atr=1.0,
        state_exec_idx=None,
        state_exec_ms=None,
        outcome_end_idx=0,
        outcome_end_ms=exit_ms,
        outcome_price=outcome,
        outcome_reason=reason,
        funding_per_unit=0.0,
        year=2022,
    )


def synthetic_market(start_ms: int, minutes: int = 20):
    starts = np.arange(start_ms, start_ms + minutes * r.MIN_MS, r.MIN_MS, dtype=np.int64)
    x = pd.DataFrame(
        {
            "start_time_ms": starts,
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "mark_open": 100.0,
        }
    )
    f = pd.DataFrame(columns=["timestamp_ms", "cum_coeff"])
    return {"BTCUSDT": x}, {"BTCUSDT": f}


def test_global_slot_reroutes_after_parent_event_deletion():
    t0 = int(pd.Timestamp("2022-01-01T00:01:00Z").timestamp() * 1000)
    events = [
        synthetic_event("winner", t0, t0 + 10 * r.MIN_MS, 101.5),
        synthetic_event("blocked", t0 + r.MIN_MS, t0 + 2 * r.MIN_MS, 99.0, "stop"),
    ]
    xmap, fmap = synthetic_market(t0 - r.MIN_MS)
    base, _, _ = r.replay(events, xmap, fmap, 0, 2022)
    rerouted, _, _ = r.replay(events, xmap, fmap, 0, 2022, {"winner"})
    assert base.event_key.tolist() == ["winner"]
    assert rerouted.event_key.tolist() == ["blocked"]


def test_year_boundary_is_marked_not_completed_with_future_outcome():
    entry_ms = int(pd.Timestamp("2022-12-31T23:58:00Z").timestamp() * 1000)
    future_exit = int(pd.Timestamp("2023-01-01T00:10:00Z").timestamp() * 1000)
    e = synthetic_event("cross-year", entry_ms, future_exit, 101.5)
    starts = np.array(
        [
            entry_ms - r.MIN_MS,
            entry_ms,
            int(pd.Timestamp("2022-12-31T23:59:00Z").timestamp() * 1000),
        ],
        dtype=np.int64,
    )
    x = pd.DataFrame(
        {
            "start_time_ms": starts,
            "open": [100.0, 100.0, 100.2],
            "high": [100.0, 100.0, 100.2],
            "low": [100.0, 100.0, 100.2],
            "close": [100.0, 100.0, 100.2],
            "mark_open": [100.0, 100.0, 100.2],
        }
    )
    f = pd.DataFrame(columns=["timestamp_ms", "cum_coeff"])
    t, m, _ = r.replay([e], {"BTCUSDT": x}, {"BTCUSDT": f}, 0, 2022)
    assert len(t) == 1
    assert not bool(t.completed.iloc[0])
    assert t.reason.iloc[0] == "boundary_mark"
    assert m["completed_trades"] == 0


def test_frozen_contract_constants():
    assert r.SPONSOR_Z == 2.2706072565238586
    assert r.YEARS_PRE == (2021, 2022)
    assert r.COSTS == (0, 12, 18, 24)
