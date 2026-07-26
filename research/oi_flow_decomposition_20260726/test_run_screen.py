from __future__ import annotations

import numpy as np
import pandas as pd

import run_screen as r


def test_candidate_grid_is_frozen_and_unique() -> None:
    grid = r.candidate_grid()
    assert len(grid) == 1152
    assert len({candidate.candidate_id for candidate in grid}) == len(grid)


def test_feature_frame_uses_completed_windows() -> None:
    day = r.synthetic_day()
    frame = r.build_feature_frame(day, 1)
    assert not frame.empty
    assert (frame["decision_us"] > frame.index).all()
    assert np.isfinite(frame["spread"]).all()


def test_resolve_event_obeys_entry_latency() -> None:
    day = r.synthetic_day()
    decision = int(day.one_second.index[100] + 1_000_000)
    event = r.Event(
        day.day, day.symbol, "opening_continuation", 1, decision, 1,
        100.2, 100.3, 100.31, 100.19, 100.3, 0.01,
        0.001, 4.0, 0.8, 5.0, 5.0, 0.8, 10.0,
    )
    trade = r.resolve_event(event, r.ExecutionData(day.quotes, day.funding_events), 500, 1.0)
    assert trade.entry_us >= decision + 500_000
    assert trade.exit_us >= trade.entry_us


def test_global_slot_blocks_overlap() -> None:
    day = r.synthetic_day()
    decision = int(day.one_second.index[100] + 1_000_000)
    event = r.Event(
        day.day, day.symbol, "opening_continuation", 1, decision, 1,
        100.2, 100.3, 100.31, 100.19, 100.3, 0.01,
        0.001, 4.0, 0.8, 5.0, 5.0, 0.8, 10.0,
    )
    first = r.resolve_event(event, r.ExecutionData(day.quotes, day.funding_events), 100, 1.0)
    second = r.ResolvedTrade(**{**r.asdict(first), "event_key": "other", "score": 9.0})
    assert len(r.enforce_global_slot([first, second])) == 1


def test_punitive_source_boundary_is_not_favorable() -> None:
    quotes = r.QuoteBook(
        ts=np.asarray([1_000_000, 1_100_000], dtype=np.int64),
        bid=np.asarray([99.9, 99.9]),
        bid_size=np.asarray([10.0, 10.0]),
        ask=np.asarray([100.1, 100.1]),
        ask_size=np.asarray([10.0, 10.0]),
    )
    event = r.Event(
        "2023-01-01", "BTCUSDT", "opening_continuation", 1, 1_000_000, 1,
        99.8, 100.0, 100.1, 99.7, 100.0, 0.2,
        0.001, 4.0, 0.8, 5.0, 5.0, 0.8, 10.0,
    )
    market = r.ExecutionData(
        quotes, pd.DataFrame(columns=["funding_us", "observed_us", "funding_rate"])
    )
    trade = r.resolve_event(event, market, 100, 2.0)
    assert trade.unresolved is True
    assert trade.gross_return <= 0


def test_performance_applies_cost_and_risk_cap() -> None:
    trade = r.ResolvedTrade(
        "x", "2023-01-01", "BTCUSDT", "opening_continuation",
        1, 2, 3, 1, 100.0, 101.0, 99.0, 101.0,
        10.0, 10.0, 0.01, "target", 0, 0, 0.0, 0, False, 1.0,
    )
    low = r.performance([trade], 12.0, ("2023-01-01",))
    high = r.performance([trade], 24.0, ("2023-01-01",))
    assert low["total_return"] > high["total_return"]
    assert low["maximum_drawdown"] >= 0


def test_candidate_specific_transition_is_not_hidden_by_lower_threshold() -> None:
    base = dict(
        day="2023-01-01", symbol="BTCUSDT", family="opening_continuation",
        window_seconds=1, side=1, event_first=100.0, event_last=100.1,
        event_high=100.2, event_low=99.9, decision_mid=100.1,
        decision_spread=0.01, oi_rel=0.001, flow_imbalance=0.8,
        flow_size=5.0, move_spreads=6.0, close_efficiency=0.8, score=10.0,
    )
    low = r.Event(decision_us=1_000_000, oi_z=2.5, **base)
    high = r.Event(decision_us=2_000_000, oi_z=4.5, **base)
    candidate = r.Candidate("opening_continuation", 1, 4.0, 0.65, 4.0, 5.0, 100, 1.0)
    selected = r.candidate_transition_events([low, high], candidate)
    assert [event.decision_us for event in selected] == [2_000_000]


def test_funding_is_included_with_correct_sign() -> None:
    events = pd.DataFrame({
        "funding_us": [2_000_000], "observed_us": [1_900_000], "funding_rate": [0.001]
    })
    long_adjustment, count = r._funding_adjustment(events, 1_000_000, 3_000_000, 1)
    short_adjustment, _ = r._funding_adjustment(events, 1_000_000, 3_000_000, -1)
    assert count == 1
    assert long_adjustment == -0.001
    assert short_adjustment == 0.001


def test_derivative_ticker_keeps_latest_pre_settlement_rate(tmp_path) -> None:
    import csv
    import gzip

    path = tmp_path / "ticker.csv.gz"
    fields = [
        "exchange", "symbol", "timestamp", "local_timestamp", "funding_timestamp",
        "funding_rate", "predicted_funding_rate", "open_interest", "last_price",
        "index_price", "mark_price",
    ]
    rows = [
        ["bybit", "BTCUSDT", "1000000", "1000000", "5000000", "0.0001", "", "1000", "100", "100", "100"],
        ["bybit", "BTCUSDT", "2000000", "2000000", "5000000", "0.0002", "", "1001", "101", "101", "101"],
        ["bybit", "BTCUSDT", "4000000", "4000000", "5000000", "0.0003", "", "1002", "102", "102", "102"],
    ]
    with gzip.open(path, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        writer.writerows(rows)
    oi, funding = r.read_derivative_ticker(path)
    assert list(oi["open_interest"]) == [1000.0, 1001.0, 1002.0]
    assert funding.iloc[0]["funding_rate"] == 0.0003
