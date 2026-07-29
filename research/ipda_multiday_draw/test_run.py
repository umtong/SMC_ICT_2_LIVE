from types import SimpleNamespace

import numpy as np
import pandas as pd

from research.ipda_multiday_draw.run import DAY_MS, MINUTE_MS, prepare_daily, simulate_one


def test_day_start_range_uses_completed_prior_days_only():
    rows = []
    for i in range(62):
        rows.append(
            dict(
                start_time_ms=i * DAY_MS,
                open=100.0,
                high=100.0 + i,
                low=50.0 - i,
                close=75.0,
                is_complete=True,
            )
        )
    frame = pd.DataFrame(rows)
    prepared = prepare_daily(frame)
    row = prepared.iloc[-1]
    assert row.high20 == frame.iloc[-21:-1].high.max()
    assert row.low20 == frame.iloc[-21:-1].low.min()
    assert row.old_high20 == frame.iloc[-22:-2].high.max()
    assert row.old_low20 == frame.iloc[-22:-2].low.min()


def test_500ms_activation_cannot_use_minute_open_at_decision_time():
    decision = 300_000
    minute = pd.DataFrame(
        {
            "start_time_ms": [decision, decision + MINUTE_MS, decision + 2 * MINUTE_MS],
            "open": [100.0, 101.0, 102.0],
            "high": [100.5, 102.0, 106.0],
            "low": [99.5, 100.5, 101.0],
            "close": [100.0, 101.5, 105.0],
        }
    )
    event = SimpleNamespace(
        symbol="BTCUSDT",
        day_start_ms=0,
        family="accepted_expansion",
        horizon=40,
        direction=1,
        target=105.0,
        source_boundary=99.0,
        state_strength=1.0,
        decision_time_ms=decision,
        signal_start_ms=0,
        signal_close=100.0,
        stop=98.0,
        atr=1.0,
        body_atr=1.0,
        range_atr=1.0,
        close_loc=1.0,
        rr_at_signal=2.0,
        prior_close=100.0,
        range_low=90.0,
        range_high=105.0,
        _asdict=lambda: {
            "symbol": "BTCUSDT",
            "day_start_ms": 0,
            "family": "accepted_expansion",
            "horizon": 40,
            "direction": 1,
            "target": 105.0,
            "source_boundary": 99.0,
            "state_strength": 1.0,
            "decision_time_ms": decision,
            "signal_start_ms": 0,
            "signal_close": 100.0,
            "stop": 98.0,
            "atr": 1.0,
            "body_atr": 1.0,
            "range_atr": 1.0,
            "close_loc": 1.0,
            "rr_at_signal": 2.0,
            "prior_close": 100.0,
            "range_low": 90.0,
            "range_high": 105.0,
        },
    )
    result = simulate_one(event, minute, decision + 3 * MINUTE_MS)
    assert result["filled"]
    assert result["entry_time_ms"] == decision + MINUTE_MS
    assert result["entry_price"] == 101.0


def test_same_minute_stop_and_target_is_stop_first():
    decision = 300_000
    minute = pd.DataFrame(
        {
            "start_time_ms": [decision, decision + MINUTE_MS],
            "open": [100.0, 100.0],
            "high": [100.2, 106.0],
            "low": [99.8, 97.0],
            "close": [100.0, 100.0],
        }
    )
    payload = dict(
        symbol="BTCUSDT", day_start_ms=0, family="accepted_expansion", horizon=40,
        direction=1, target=105.0, source_boundary=99.0, state_strength=1.0,
        decision_time_ms=decision, signal_start_ms=0, signal_close=100.0, stop=98.0,
        atr=1.0, body_atr=1.0, range_atr=1.0, close_loc=1.0, rr_at_signal=2.0,
        prior_close=100.0, range_low=90.0, range_high=105.0,
    )
    event = SimpleNamespace(**payload, _asdict=lambda: payload.copy())
    result = simulate_one(event, minute, decision + 2 * MINUTE_MS)
    assert result["filled"]
    assert result["outcome"] == -1
    assert np.isclose(result["net_r"], -1.0)
