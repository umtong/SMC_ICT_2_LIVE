from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

import run as mm


def base_candidate(**overrides) -> mm.CandidateTrade:
    payload = dict(
        config_id="cfg",
        event_key="event-a",
        symbol="BTCUSDT",
        side=1,
        entry_i=1,
        exit_i=3,
        entry_time="2022-01-01T00:05:00+00:00",
        exit_time="2022-01-01T00:15:00+00:00",
        entry_price=100.0,
        exit_price=104.0,
        stop_price=98.0,
        target_price=104.0,
        exit_reason="original_consolidation_target",
        score=3.0,
        quote_volume_prior=10_000_000.0,
        open_at_boundary=False,
        oc_start="2021-12-31T20:00:00+00:00",
        oc_end="2022-01-01T00:00:00+00:00",
        break_time="2022-01-01T00:00:00+00:00",
        sweep_time="2022-01-01T00:00:00+00:00",
        smr_time="2022-01-01T00:00:00+00:00",
        shelf_count_observed=2,
        excursion_units_observed=1.0,
        displacement_atr_observed=1.2,
    )
    payload.update(overrides)
    return mm.CandidateTrade(**payload)


def execution_frame() -> pd.DataFrame:
    index = pd.date_range("2022-01-01", periods=6, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0, 101.0, 100.0, 103.0, 104.0],
            "high": [100.2, 101.2, 104.5, 101.0, 104.2, 104.5],
            "low": [99.8, 99.0, 97.5, 99.0, 102.0, 103.5],
            "close": [100.0, 101.0, 100.0, 100.5, 104.0, 104.0],
            "volume": [1_000_000.0] * 6,
            "valid": [True] * 6,
        },
        index=index,
    )
    frame["close_time"] = frame.index + pd.Timedelta(minutes=5)
    return frame


def metadata() -> dict[str, object]:
    return {
        "oc_start": "2021-12-31T20:00:00+00:00",
        "oc_end": "2022-01-01T00:00:00+00:00",
        "break_time": "2022-01-01T00:00:00+00:00",
        "sweep_time": "2022-01-01T00:00:00+00:00",
        "smr_time": "2022-01-01T00:00:00+00:00",
        "shelf_count_observed": 2,
        "excursion_units_observed": 1.0,
        "displacement_atr_observed": 1.2,
    }


def test_grid_is_exact_and_stable() -> None:
    cells = mm.configs()
    assert len(cells) == 64
    assert len({cell.config_id for cell in cells}) == 64


def test_sealed_year_is_physically_rejected() -> None:
    with pytest.raises(ValueError, match="sealed"):
        mm.month_url("BTCUSDT", 2024, 1)


def test_header_and_headerless_parsing_are_equivalent() -> None:
    body = [
        ["2022-01-01 00:00:00", "100", "101", "99", "100.5", "12"],
        ["2022-01-01 00:05:00", "100.5", "102", "100", "101", "13"],
    ]
    headerless = mm._coerce_kline(pd.DataFrame(body))
    with_header = mm._coerce_kline(pd.DataFrame([["datetime", "open", "high", "low", "close", "volume"], *body]))
    pd.testing.assert_frame_equal(headerless, with_header)


def test_pivot_is_not_available_before_right_confirmation() -> None:
    high = np.array([1, 2, 3, 5, 3, 2, 1], dtype=float)
    low = np.array([0, -1, -2, -3, -2, -1, 0], dtype=float)
    valid = np.ones(7, dtype=bool)
    ph, pl, phi, pli = mm.confirmed_pivots(high, low, valid, span=3)
    assert np.isnan(ph[:6]).all()
    assert np.isnan(pl[:6]).all()
    assert ph[6] == 5 and phi[6] == 3
    assert pl[6] == -3 and pli[6] == 3


def test_stop_wins_same_bar_target_ambiguity() -> None:
    cfg = mm.configs()[0]
    trade = mm._resolve_trade(
        execution_frame(), cfg, "BTCUSDT", 1, 1, 98.0, 104.0, 3.0, metadata()
    )
    assert trade.exit_reason == "stop_first"
    assert trade.exit_price == 98.0


def test_source_gap_after_entry_receives_structural_stop() -> None:
    frame = execution_frame()
    frame.loc[frame.index[2], "valid"] = False
    cfg = mm.configs()[0]
    trade = mm._resolve_trade(frame, cfg, "BTCUSDT", 1, 1, 98.0, 110.0, 3.0, metadata())
    assert trade.exit_reason == "source_gap_structural_stop"
    assert trade.exit_price == 98.0


def test_no_elapsed_time_liquidation_at_boundary() -> None:
    frame = execution_frame()
    frame.loc[:, "high"] = np.minimum(frame["high"], 103.0)
    frame.loc[:, "low"] = np.maximum(frame["low"], 99.0)
    cfg = mm.configs()[0]
    trade = mm._resolve_trade(frame, cfg, "BTCUSDT", 1, 1, 98.0, 110.0, 3.0, metadata())
    assert trade.exit_reason == "boundary_mark"
    assert trade.open_at_boundary is True
    assert trade.exit_i == len(frame) - 1


def test_global_slot_releases_for_next_trade_and_uses_score_for_ties() -> None:
    first_low = base_candidate(event_key="low", score=1.0, exit_time="2022-01-01T00:20:00+00:00")
    first_high = replace(first_low, event_key="high", score=5.0, symbol="ETHUSDT")
    later = base_candidate(
        event_key="later",
        entry_time="2022-01-01T00:20:00+00:00",
        exit_time="2022-01-01T00:30:00+00:00",
    )
    selected = mm.select_global([first_low, later, first_high])
    assert [item.event_key for item in selected] == ["high", "later"]


def test_removed_winner_releases_slot_to_alternative() -> None:
    winner = base_candidate(event_key="winner", score=5.0, exit_time="2022-01-01T00:20:00+00:00")
    blocked = replace(winner, event_key="blocked", score=1.0, symbol="ETHUSDT")
    selected = mm.select_global([winner, blocked])
    replay = mm.select_global([winner, blocked], {"winner"})
    assert [item.event_key for item in selected] == ["winner"]
    assert [item.event_key for item in replay] == ["blocked"]


def test_cost_stress_reduces_account_return() -> None:
    selected = [base_candidate()]
    low, low_state = mm.replay_account(selected, 12.0)
    high, high_state = mm.replay_account(selected, 24.0)
    assert low and high
    assert float(low_state["nav"]) > float(high_state["nav"])


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
    assert mm.preliminary_pass(by_cost) is False


def test_complete_mmbm_lifecycle_produces_next_bar_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    index = pd.date_range("2022-02-01", periods=20, freq="5min", tz="UTC")
    close = np.array([
        101.0, 99.0, 99.2, 99.0, 98.4, 98.2, 98.0, 97.2, 97.2, 99.0,
        98.4, 98.5, 100.0, 103.0, 107.0, 110.2, 110.0, 110.0, 110.0, 110.0,
    ])
    open_ = np.array([
        101.0, 100.5, 99.0, 99.2, 99.0, 98.4, 98.2, 98.0, 96.8, 97.2,
        98.2, 98.5, 98.5, 100.0, 103.0, 107.0, 110.2, 110.0, 110.0, 110.0,
    ])
    high = np.maximum(open_, close) + 0.2
    low = np.minimum(open_, close) - 0.2
    low[8] = 94.0
    high[15] = 110.5
    frame = pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": np.full(20, 1_000_000.0), "valid": np.ones(20, dtype=bool),
        "atr5": np.ones(20),
        "pivot_high_confirmed": np.full(20, np.nan),
        "pivot_low_confirmed": np.full(20, np.nan),
        "pivot_high_origin": np.full(20, -1, dtype=np.int64),
        "pivot_low_origin": np.full(20, -1, dtype=np.int64),
    }, index=index)
    frame["close_time"] = frame.index + pd.Timedelta(minutes=5)
    frame.loc[index[3], ["pivot_high_confirmed", "pivot_high_origin"]] = [99.5, 2]
    frame.loc[index[4], ["pivot_low_confirmed", "pivot_low_origin"]] = [98.0, 3]
    frame.loc[index[6], ["pivot_high_confirmed", "pivot_high_origin"]] = [98.5, 5]
    frame.loc[index[7], ["pivot_low_confirmed", "pivot_low_origin"]] = [97.0, 6]

    mapped = pd.DataFrame({
        "oc_valid": [True] + [False] * 19,
        "oc_high": [110.0] * 20,
        "oc_low": [100.0] * 20,
        "oc_mid": [105.0] * 20,
        "oc_range": [10.0] * 20,
        "oc_start": [pd.Timestamp("2022-01-31T20:00:00Z")] * 20,
        "oc_end": [pd.Timestamp("2022-02-01T00:00:00Z")] * 20,
    }, index=index)
    monkeypatch.setattr(mm, "original_consolidations", lambda *_args, **_kwargs: mapped)
    cfg = mm.Config(4, 1.5, 2, 0.5, 0.8, "displacement_body_midpoint")
    trades = mm.detect_trades(frame, cfg, "BTCUSDT")
    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_time == index[11].isoformat()
    assert trade.exit_reason == "original_consolidation_target"
    assert trade.shelf_count_observed == 2
    assert trade.side == 1
