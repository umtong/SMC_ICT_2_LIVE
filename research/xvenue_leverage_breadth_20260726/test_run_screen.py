from __future__ import annotations

import numpy as np
import pandas as pd

import run_screen as r


def test_candidate_grid_is_frozen_and_unique() -> None:
    grid = r.candidate_grid()
    assert len(grid) == 1920
    assert len({candidate.candidate_id for candidate in grid}) == 1920


def test_dataset_url_keeps_venue_and_symbol() -> None:
    assert "/binance-futures/derivative_ticker/" in r.dataset_url(
        r.BINANCE, "derivative_ticker", "2023-01-01", "BTCUSDT"
    )
    assert "/bybit/quotes/" in r.dataset_url(
        r.BYBIT, "quotes", "2023-01-01", "ETHUSDT"
    )


def test_feature_frame_uses_completed_boundaries() -> None:
    day = r.synthetic_day()
    frame = r.build_feature_frame(day, 1)
    assert not frame.empty
    assert (frame["decision_us"] > frame.index).all()
    assert np.isfinite(frame["spread"]).all()
    assert (frame["spread"] > 0).all()


def _event_frame() -> pd.DataFrame:
    index = pd.Index([1_000_000], name="second_us")
    return pd.DataFrame({
        "decision_us": [2_000_000],
        "bn_oi_rel": [0.002],
        "bb_oi_rel": [0.0018],
        "bn_oi_z": [3.0],
        "bb_oi_z": [2.8],
        "bn_flow": [0.8],
        "bb_flow": [0.7],
        "bn_flow_size": [4.0],
        "bb_flow_size": [3.5],
        "bn_flow_direction": [1.0],
        "bb_flow_direction": [1.0],
        "common_direction": [1.0],
        "common_flow": [0.7],
        "common_flow_size": [3.5],
        "bn_log_return": [0.001],
        "bb_log_return": [0.0009],
        "bn_move_spreads": [9.0],
        "bb_move_spreads": [8.0],
        "common_move_spreads": [8.5],
        "cross_gap_spreads": [2.0],
        "bb_range_spreads": [10.0],
        "bb_close_efficiency": [0.9],
        "oi_balance_ratio": [2.8 / 3.0],
        "binance_dominance_share": [3.0 / 5.8],
        "bybit_dominance_share": [2.8 / 5.8],
        "mid": [100.0],
        "spread": [0.01],
        "bb_first": [99.91],
        "bb_last": [100.0],
        "bb_high": [100.01],
        "bb_low": [99.90],
    }, index=index)


def test_common_opening_event_is_detected() -> None:
    events = r.raw_events(
        _event_frame(), "2023-01-01", "BTCUSDT",
        "common_opening_continuation", 1,
    )
    assert len(events) == 1
    assert events[0].side == 1
    assert events[0].venue_relation > 0.9


def test_venue_relation_threshold_semantics() -> None:
    event = r.raw_events(
        _event_frame(), "2023-01-01", "BTCUSDT",
        "common_opening_continuation", 1,
    )[0]
    loose = r.Candidate(
        "common_opening_continuation", 1, 1.5, 0.35, 1.5, 1.5, 0.35, 100, 1.0
    )
    strict = r.Candidate(
        "common_opening_continuation", 1, 1.5, 0.35, 1.5, 1.5, 0.99, 100, 1.0
    )
    assert r.event_matches(event, loose)
    assert not r.event_matches(event, strict)


def test_candidate_specific_transition_preserves_later_crossing() -> None:
    base = dict(
        day="2023-01-01", symbol="BTCUSDT",
        family="common_opening_continuation", window_seconds=1, side=1,
        event_first=100.0, event_last=100.1, event_high=100.2,
        event_low=99.9, decision_mid=100.1, decision_spread=0.01,
        oi_rel=0.001, flow_imbalance=0.8, flow_size=4.0,
        move_spreads=5.0, close_efficiency=0.8, score=10.0,
        venue_relation=0.8, binance_oi_z=3.0, bybit_oi_z=3.0,
    )
    low = r.Event(decision_us=1_000_000, oi_z=1.8, **base)
    high = r.Event(decision_us=3_000_000, oi_z=3.0, **base)
    candidate = r.Candidate(
        "common_opening_continuation", 1, 2.5, 0.60, 3.0, 4.0, 0.65, 100, 1.0
    )
    selected = r.candidate_transition_events([low, high], candidate)
    assert [event.decision_us for event in selected] == [3_000_000]


def test_resolve_event_obeys_latency() -> None:
    day = r.synthetic_day()
    event = r.Event(
        day.day, day.symbol, "common_opening_continuation", 1,
        int(day.bybit.one_second.index[2500] + 1_000_000), 1,
        100.0, 100.1, 100.2, 99.9, 100.1, 0.01,
        0.001, 3.0, 0.8, 4.0, 5.0, 0.8, 10.0,
        0.8, 3.0, 3.0,
    )
    assert day.bybit.quotes is not None
    trade = r.resolve_event(
        event, r.ExecutionData(day.bybit.quotes, day.bybit.funding_events),
        500, 1.0,
    )
    assert trade.entry_us >= event.decision_us + 500_000
    assert trade.exit_us >= trade.entry_us


def test_funding_sign_is_correct() -> None:
    funding = pd.DataFrame({
        "funding_us": [2_000_000],
        "observed_us": [1_900_000],
        "funding_rate": [0.001],
    })
    long_adjustment, count = r._funding_adjustment(
        funding, 1_000_000, 3_000_000, 1
    )
    short_adjustment, _ = r._funding_adjustment(
        funding, 1_000_000, 3_000_000, -1
    )
    assert count == 1
    assert long_adjustment == -0.001
    assert short_adjustment == 0.001


def test_global_slot_and_cost_monotonicity() -> None:
    trade = r.ResolvedTrade(
        "x", "2023-01-01", "BTCUSDT", "common_opening_continuation",
        1, 2, 3, 1, 100.0, 101.0, 99.0, 101.0,
        10.0, 10.0, 0.01, "target", 0, 0, 0.0, 0, False, 1.0,
    )
    duplicate = r.ResolvedTrade(**{**r.asdict(trade), "event_key": "y", "score": 2.0})
    assert len(r.enforce_global_slot([trade, duplicate])) == 1
    low = r.performance([trade], 12.0, ("2023-01-01",))
    high = r.performance([trade], 24.0, ("2023-01-01",))
    assert low["total_return"] > high["total_return"]
