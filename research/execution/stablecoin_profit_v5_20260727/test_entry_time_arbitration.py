from __future__ import annotations

import numpy as np
import pandas as pd

import run as base


def test_same_executable_entry_competes_before_slot_occupancy() -> None:
    rows = pd.DataFrame(
        [
            {
                "event_id": "earlier-low-ev",
                "symbol": "BTCUSDT",
                "decision_ms": 1_000,
                "entry_ms": 60_000,
                "synthetic_ev_bps": 10.0,
                "synthetic_exit_ms": 120_000,
            },
            {
                "event_id": "later-high-ev",
                "symbol": "ETHUSDT",
                "decision_ms": 30_000,
                "entry_ms": 60_000,
                "synthetic_ev_bps": 25.0,
                "synthetic_exit_ms": 180_000,
            },
        ]
    )
    bars = {
        "BTCUSDT": pd.DataFrame(),
        "ETHUSDT": pd.DataFrame(),
    }
    funding = {
        "BTCUSDT": pd.DataFrame(),
        "ETHUSDT": pd.DataFrame(),
    }
    original = base.trade_from_row

    def fake_trade_from_row(row, _p, _cost, _bars, _funding):
        return base.Trade(
            event_id=str(row["event_id"]),
            symbol=str(row["symbol"]),
            decision_ms=int(row["decision_ms"]),
            entry_ms=int(row["entry_ms"]),
            exit_ms=int(row["synthetic_exit_ms"]),
            side=1,
            entry=100.0,
            exit_price=101.0,
            stop_price=99.0,
            target_price=101.0,
            stop_fraction=0.01,
            gross_fraction=0.01,
            funding_fraction=0.0,
            model_probability_up=0.6,
            ev_bps=float(row["synthetic_ev_bps"]),
            exit_reason="TARGET",
            ambiguous=False,
        )

    try:
        base.trade_from_row = fake_trade_from_row
        accepted = base.route(
            rows,
            np.array([0.6, 0.6], dtype=float),
            bars,
            funding,
            24.0,
        )
    finally:
        base.trade_from_row = original

    assert [trade.event_id for trade in accepted] == ["later-high-ev"]
    assert accepted[0].entry_ms == 60_000
