from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

import run as lm


def config(**overrides) -> lm.Config:
    payload = dict(
        pivot_span=2,
        minimum_touches=2,
        maximum_pool_age_hours=24,
        minimum_mass_ratio=1.5,
        minimum_displacement_atr=0.5,
        mode="rejection",
        minimum_reward_risk=2.0,
    )
    payload.update(overrides)
    return lm.Config(**payload)


def frame() -> pd.DataFrame:
    index = pd.date_range("2022-01-01", periods=8, freq="5min", tz="UTC")
    result = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 102.0, 104.0, 106.0, 107.0, 107.0],
            "high": [100.2, 101.0, 103.0, 105.0, 108.5, 108.5, 108.0, 108.0],
            "low": [99.8, 97.0, 99.0, 101.0, 103.0, 105.0, 106.0, 106.0],
            "close": [100.0, 99.5, 102.0, 104.0, 108.0, 107.0, 107.0, 107.0],
            "volume": [1_000_000.0] * 8,
            "valid": [True] * 8,
            "atr5": [1.0] * 8,
            "quote_volume": [100_000_000.0] * 8,
            "volume_ratio": [1.0] * 8,
        },
        index=index,
    )
    result["close_time"] = result.index + pd.Timedelta(minutes=5)
    return result


def target(side: int, level: float, mass: float = 30.0, touches: float = 3.0) -> lm.PoolSnapshot:
    return lm.PoolSnapshot(
        pool_id=f"target-{side}-{level}",
        side=side,
        level=level,
        mass=mass,
        touches=touches,
        htf_hits=0,
        age_hours=10.0,
    )


def event(**overrides) -> lm.RawSweepEvent:
    payload = dict(
        event_key="evt",
        symbol="BTCUSDT",
        pivot_span=2,
        event_i=1,
        event_time="2022-01-01T00:05:00+00:00",
        sweep_side=-1,
        pool_level=98.0,
        swept_mass=10.0,
        swept_touches=2.0,
        swept_age_hours=8.0,
        open_price=99.0,
        high_price=101.0,
        low_price=97.0,
        close_price=99.5,
        atr=1.0,
        body_atr=0.5,
        close_location=0.625,
        quote_volume_prior=100_000_000.0,
        high_targets=(target(1, 108.0),),
        low_targets=(target(-1, 92.0),),
    )
    payload.update(overrides)
    return lm.RawSweepEvent(**payload)


def candidate(**overrides) -> lm.CandidateTrade:
    payload = dict(
        config_id="cfg",
        event_key="a",
        symbol="BTCUSDT",
        mode="rejection",
        side=1,
        entry_i=1,
        exit_i=3,
        entry_time="2022-01-01T00:05:00+00:00",
        exit_time="2022-01-01T00:15:00+00:00",
        entry_price=100.0,
        exit_price=104.0,
        stop_price=98.0,
        target_price=104.0,
        exit_reason="liquidity_pool_target",
        score=3.0,
        quote_volume_prior=10_000_000.0,
        open_at_boundary=False,
        swept_pool_level=98.0,
        swept_pool_mass=10.0,
        target_pool_level=104.0,
        target_pool_mass=30.0,
        mass_ratio=3.0,
        swept_touches=2.0,
        target_touches=3.0,
        body_atr=1.0,
    )
    payload.update(overrides)
    return lm.CandidateTrade(**payload)


def test_grid_is_exact() -> None:
    cells = lm.configs()
    assert len(cells) == 128
    assert len({cell.config_id for cell in cells}) == 128


def test_sealed_year_is_rejected() -> None:
    with pytest.raises(ValueError, match="sealed"):
        lm.month_url("BTCUSDT", 2024, 1)


def test_header_and_headerless_parse_equally() -> None:
    body = [
        ["2022-01-01 00:00:00", "100", "101", "99", "100.5", "12"],
        ["2022-01-01 00:05:00", "100.5", "102", "100", "101", "13"],
    ]
    a = lm._coerce_kline(pd.DataFrame(body))
    b = lm._coerce_kline(pd.DataFrame([["datetime", "open", "high", "low", "close", "volume"], *body]))
    pd.testing.assert_frame_equal(a, b)


def test_pivot_requires_right_confirmation() -> None:
    high = np.array([1, 2, 3, 5, 3, 2, 1], float)
    low = np.array([0, -1, -2, -3, -2, -1, 0], float)
    valid = np.ones(7, bool)
    ph, pl, phi, pli = lm.confirmed_pivots(high, low, valid, 3)
    assert np.isnan(ph[:6]).all() and np.isnan(pl[:6]).all()
    assert ph[6] == 5 and phi[6] == 3
    assert pl[6] == -3 and pli[6] == 3


def test_pool_clusters_and_mass_increases() -> None:
    pools: list[lm.LiquidityPool] = []
    lm.add_pool_observation(pools, 1, 100.0, 10, 1.0, 1.0, 1.0, False)
    first = lm.pool_mass(pools[0], 10)
    lm.add_pool_observation(pools, 1, 100.05, 20, 1.0, 4.0, 1.0, False)
    second = lm.pool_mass(pools[0], 20)
    assert len(pools) == 1
    assert pools[0].touches == 2.0
    assert second > first


def test_pivot_confirmed_on_current_close_cannot_be_swept_same_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    f = frame().iloc[:3].copy()
    f.loc[f.index[1], "high"] = 106.0
    monkeypatch.setattr(lm, "pivot_events", lambda *_: {1: [(1, 105.0, 1.0, 2.0, True)]})
    events = lm.build_sweep_events(f, "BTCUSDT", 2)
    assert events == []


def test_bar_consuming_both_sides_is_not_ordered_favorably(monkeypatch: pytest.MonkeyPatch) -> None:
    f = frame().iloc[:3].copy()
    f.loc[f.index[1], ["high", "low"]] = [106.0, 94.0]
    monkeypatch.setattr(
        lm,
        "pivot_events",
        lambda *_: {0: [(1, 105.0, 1.0, 2.0, True), (-1, 95.0, 1.0, 2.0, True)]},
    )
    events = lm.build_sweep_events(f, "BTCUSDT", 2)
    assert events == []


def test_rejection_routes_to_dense_opposite_pool() -> None:
    trades = lm.candidates_from_events(frame(), [event()], config())
    assert len(trades) == 1
    trade = trades[0]
    assert trade.side == 1
    assert trade.target_price == 108.0
    assert trade.mass_ratio == 3.0
    assert trade.exit_reason == "liquidity_pool_target"


def test_acceptance_routes_to_next_same_side_pool() -> None:
    ev = event(
        sweep_side=1,
        pool_level=101.0,
        swept_mass=10.0,
        swept_touches=2.0,
        open_price=100.0,
        high_price=102.5,
        low_price=100.5,
        close_price=102.0,
        body_atr=2.0,
        close_location=0.75,
        high_targets=(target(1, 108.0),),
        low_targets=(target(-1, 95.0),),
    )
    f = frame()
    f.loc[f.index[2], "open"] = 102.2
    f.loc[f.index[2], "high"] = max(float(f.loc[f.index[2], "high"]), 103.0)
    f.loc[f.index[2], "low"] = min(float(f.loc[f.index[2], "low"]), 102.0)
    trades = lm.candidates_from_events(f, [ev], config(mode="continuation", minimum_reward_risk=2.0))
    assert len(trades) == 1
    assert trades[0].side == 1 and trades[0].target_price == 108.0


def test_mass_ratio_blocks_weak_target() -> None:
    weak = event(high_targets=(target(1, 108.0, mass=12.0),))
    assert lm.candidates_from_events(frame(), [weak], config(minimum_mass_ratio=1.5)) == []


def test_target_age_blocks_stale_pool() -> None:
    stale = replace(target(1, 108.0), age_hours=100.0)
    assert lm.candidates_from_events(frame(), [event(high_targets=(stale,))], config(maximum_pool_age_hours=24)) == []


def test_stop_wins_same_bar_target() -> None:
    f = frame()
    f.loc[f.index[2], ["high", "low"]] = [109.0, 96.0]
    trade = lm._resolve_trade(f, config(), event(), 1, target(1, 108.0), 96.95)
    assert trade.exit_reason == "stop_first"
    assert trade.exit_price == 96.95


def test_source_gap_receives_structural_stop() -> None:
    f = frame()
    f.loc[f.index[2], "valid"] = False
    trade = lm._resolve_trade(f, config(), event(), 1, target(1, 108.0), 96.95)
    assert trade.exit_reason == "source_gap_structural_stop"


def test_no_elapsed_time_exit() -> None:
    f = frame()
    f.loc[:, "high"] = np.minimum(f["high"], 107.0)
    f.loc[:, "low"] = np.maximum(f["low"], 98.0)
    far = target(1, 120.0)
    trade = lm._resolve_trade(f, config(), event(high_targets=(far,)), 1, far, 96.95)
    assert trade.exit_reason == "boundary_mark"
    assert trade.open_at_boundary is True


def test_global_slot_and_counterfactual_release() -> None:
    winner = candidate(event_key="winner", score=5.0, exit_time="2022-01-01T00:20:00+00:00")
    blocked = replace(winner, event_key="blocked", symbol="ETHUSDT", score=1.0)
    later = candidate(
        event_key="later",
        entry_time="2022-01-01T00:20:00+00:00",
        exit_time="2022-01-01T00:30:00+00:00",
    )
    assert [x.event_key for x in lm.select_global([winner, blocked, later])] == ["winner", "later"]
    assert [x.event_key for x in lm.select_global([winner, blocked], {"winner"})] == ["blocked"]


def test_cost_stress_reduces_nav() -> None:
    selected = [candidate()]
    _, low = lm.replay_account(selected, 12.0)
    _, high = lm.replay_account(selected, 24.0)
    assert float(low["nav"]) > float(high["nav"])


def test_open_position_cannot_pass_gate() -> None:
    passing = {
        "terminal_account_loss": False,
        "completed_trades": 100,
        "total_return": 0.2,
        "median_trade_bps": 2.0,
        "profit_factor": 1.5,
        "maximum_drawdown": 0.1,
        "first_half_return": 0.1,
        "second_half_return": 0.1,
        "top_five_positive_pnl_share": 0.2,
        "open_position_count": 1,
    }
    by_cost = {12.0: dict(passing), 18.0: dict(passing), 24.0: dict(passing)}
    assert lm.preliminary_pass(by_cost) is False
