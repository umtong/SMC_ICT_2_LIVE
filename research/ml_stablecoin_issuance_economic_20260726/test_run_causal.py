from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import run_causal as m


def flat_minute_frame(start: str, periods: int = 300) -> pd.DataFrame:
    times = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "open_time_ms": times.view("int64") // 1_000_000,
            "open": np.full(periods, 100.0),
            "high": np.full(periods, 101.0),
            "low": np.full(periods, 99.0),
            "close": np.full(periods, 100.0),
            "quote_volume": np.full(periods, 1_000_000.0),
        }
    )


def source_event(frame: pd.DataFrame, minute_index: int = 100) -> pd.DataFrame:
    available_ms = int(frame.iloc[minute_index]["open_time_ms"]) + 30_000
    return pd.DataFrame(
        [
            {
                "event_id": "event-1",
                "token": "USDT",
                "direction": "MINT",
                "amount_usd": 100_000_000.0,
                "block_timestamp": available_ms // 1_000 - 144,
                "available_timestamp_12": available_ms // 1_000,
                "available_timestamp_64": available_ms // 1_000 + 624,
            }
        ]
    )


def empty_funding() -> dict[str, pd.DataFrame]:
    frame = pd.DataFrame({"time_ms": [], "rate": []})
    return {"BTCUSDT": frame.copy(), "ETHUSDT": frame.copy()}


def test_entry_bar_close_cannot_change_completed_features() -> None:
    base_frame = flat_minute_frame("2021-06-01", 300)
    events = source_event(base_frame)
    bars = {"BTCUSDT": base_frame.copy(), "ETHUSDT": base_frame.copy()}
    rows = m.build_rows(events, bars, empty_funding(), 12)
    assert not rows.empty
    entry_index = int(rows.iloc[0]["entry_index"])
    assert int(rows.iloc[0]["completed_feature_index"]) == entry_index - 1

    mutated = base_frame.copy()
    mutated.loc[entry_index, "close"] = 1_000.0
    mutated_bars = {"BTCUSDT": mutated.copy(), "ETHUSDT": mutated.copy()}
    mutated_rows = m.build_rows(events, mutated_bars, empty_funding(), 12)
    assert len(mutated_rows) == len(rows)

    for column in (
        "prior_15m_return",
        "prior_60m_realized_volatility",
        "prior_60m_path_efficiency",
        "btc_eth_completed_return_breadth",
    ):
        np.testing.assert_allclose(
            rows[column].to_numpy(float),
            mutated_rows[column].to_numpy(float),
            equal_nan=True,
        )


def test_unresolved_structural_path_is_marked_not_stopped() -> None:
    frame = flat_minute_frame("2021-06-01", 180)
    frame["high"] = 100.2
    frame["low"] = 99.8
    funding = pd.DataFrame({"time_ms": [], "rate": []})
    row = pd.Series(
        {
            "event_id": "mark-event",
            "symbol": "BTCUSDT",
            "decision_ms": int(frame.iloc[69]["open_time_ms"]),
            "entry_index": 70,
            "entry_ms": int(frame.iloc[70]["open_time_ms"]),
            "exit_index": 80,
            "stage_boundary_ms": int(frame.iloc[81]["open_time_ms"]),
            "entry": 100.0,
            "upper": 110.0,
            "lower": 90.0,
            "distance_to_frozen_upper_60m_liquidity": 0.10,
            "distance_to_frozen_lower_60m_liquidity": 0.10,
        }
    )
    trade = m.trade_from_row(row, 0.99, 12.0, frame, funding)
    assert trade is not None
    assert trade.exit_reason == "MARK_TO_MARKET_STAGE_BOUNDARY"
    assert trade.exit_price == pytest.approx(float(frame.iloc[80]["close"]))
    assert trade.exit_price != pytest.approx(90.0)
    assert trade.exit_ms == int(frame.iloc[81]["open_time_ms"])

    replay = m.replay(
        [trade], 12.0, "2021-06-01", "2021-06-02", 0.005, 3.0
    )
    assert replay["boundary_mark_count"] == 1
    assert replay["forced_boundary_close"] is False


def test_pre2024_advancement_uses_cost_return_and_survival_only() -> None:
    result = {
        "costs": {
            "24": {
                "total_return": 0.01,
                "liquidation": False,
                "median_trade_bps": -500.0,
                "profit_factor": 0.1,
                "winner_removed": {"total_return": -0.5},
                "first_half_return": -0.2,
                "second_half_return": 0.3,
            }
        }
    }
    gate = m.development_gate(result)
    assert gate["all"] is True

    result["costs"]["24"]["total_return"] = -0.01
    assert m.development_gate(result)["all"] is False


def test_causal_wrapper_self_test() -> None:
    m.self_test()
