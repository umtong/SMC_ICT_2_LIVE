from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

import numpy as np
import pytest

from run import (
    COSTS_BPS,
    PROHIBITED_YEARS,
    STATE_BUCKET_US,
    Action,
    QuoteBook,
    aggregate_quote_states,
    bs_price_delta_gamma,
    entry_quote,
    first_passage,
    funding_boundaries,
    implied_volatility,
    parse_option_symbol,
    replay_account,
    source_url,
)


def book_from_rows(rows: list[tuple[int, float, float]]) -> QuoteBook:
    ts = np.array([row[0] for row in rows], dtype=np.int64)
    bid = np.array([row[1] for row in rows], dtype=float)
    ask = np.array([row[2] for row in rows], dtype=float)
    amount = np.full(len(rows), 100.0)
    state = aggregate_quote_states(ts, bid, ask)
    return QuoteBook(ts, ts + 1_000, bid, ask, amount, amount, *state)


def action(**overrides: object) -> Action:
    base = Action(
        event_key="a",
        date="2022-01-01",
        symbol="BTCUSDT",
        side=1,
        entry_time_us=1_000_000,
        exit_time_us=2_000_000,
        entry_price=100.0,
        exit_price=102.0,
        stop_price=99.0,
        target_price=102.0,
        entry_top_amount=100.0,
        outcome="upper",
        exit_reason="target",
        p_upper_first=0.8,
        long_ev_bps=20.0,
        short_ev_bps=-40.0,
    )
    return Action(**{**asdict(base), **overrides})


def test_option_symbol_and_expiry_are_explicit() -> None:
    underlier, expiry, strike, kind = parse_option_symbol("ETH-6JAN23-1250-P")
    assert (underlier, strike, kind) == ("ETH", 1250.0, "P")
    assert expiry == datetime(2023, 1, 6, 8, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        parse_option_symbol("BTC-PERPETUAL")


def test_black_scholes_reconstructs_fixture_scale() -> None:
    timestamp = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
    expiry = datetime(2023, 1, 13, 8, tzinfo=timezone.utc).timestamp()
    t = (expiry - timestamp) / (365 * 86400)
    solved = implied_volatility(1193.63, 1100.0, t, 0.0108, "P")
    assert solved is not None
    iv, delta, gamma = solved
    price, _, _ = bs_price_delta_gamma(1193.63, 1100.0, t, iv, "P")
    assert abs(price / 1193.63 - 0.0108) < 1e-7
    assert abs(delta + 0.18972) < 0.03
    assert abs(gamma - 0.00231) < 0.0005


def test_first_future_quote_and_delay_limit() -> None:
    book = book_from_rows([(1_000_000, 99.9, 100.1), (1_500_000, 100.0, 100.2)])
    found = entry_quote(book, 1_100_000)
    assert found is not None and found[0] == 1_500_000
    assert entry_quote(book, 2_600_001) is None


def test_same_bucket_dual_touch_is_ambiguous() -> None:
    rows = [
        (1_000_000, 99.9, 100.1),
        (1_050_000, 102.1, 102.2),
        (1_090_000, 98.8, 99.0),
    ]
    book = book_from_rows(rows)
    label, outcome, *_ = first_passage(book, 1_000_000, 102.0, 99.0, 2_000_000)
    assert label == -1 and outcome == "both"


def test_source_gap_is_not_bridged() -> None:
    rows = [
        (1_000_000, 99.9, 100.1),
        (1_100_000, 99.9, 100.1),
        (2_300_000, 102.1, 102.2),
    ]
    book = book_from_rows(rows)
    label, outcome, *_ = first_passage(book, 1_000_000, 102.0, 99.0, 3_000_000)
    assert label == -2 and outcome == "source_gap"


def test_sealed_years_are_rejected_before_download() -> None:
    assert set(PROHIBITED_YEARS) == {2024, 2025, 2026}
    for year in PROHIBITED_YEARS:
        with pytest.raises(ValueError, match="sealed year"):
            source_url("bybit", "quotes", f"{year}-01-01", "BTCUSDT")


def test_one_global_slot_and_counterfactual_release() -> None:
    first = action(event_key="first", exit_time_us=5_000_000)
    second = action(event_key="second", entry_time_us=2_000_000, exit_time_us=3_000_000)
    baseline, _ = replay_account([first, second], 12.0)
    counterfactual, _ = replay_account([first, second], 12.0, {"first"})
    assert [trade.event_key for trade in baseline] == ["first"]
    assert [trade.event_key for trade in counterfactual] == ["second"]


def test_cost_paths_are_identical_actions_and_monotone_nav() -> None:
    values = [replay_account([action()], cost)[1] for cost in COSTS_BPS]
    assert values[0] > values[1] > values[2]


def test_boundary_stop_cannot_disappear() -> None:
    unresolved = action(
        outcome="day_boundary",
        exit_reason="conservative_boundary_stop",
        exit_price=99.0,
        exit_time_us=10_000_000,
    )
    trades, nav = replay_account([unresolved], 12.0)
    assert len(trades) == 1
    assert trades[0].exit_reason == "conservative_boundary_stop"
    assert nav < 10_000.0


def test_funding_boundaries_are_counted_in_open_interval() -> None:
    start = int(datetime(2023, 1, 1, 7, 59, tzinfo=timezone.utc).timestamp() * 1_000_000)
    end = int(datetime(2023, 1, 1, 16, 1, tzinfo=timezone.utc).timestamp() * 1_000_000)
    assert funding_boundaries(start, end) == 2
