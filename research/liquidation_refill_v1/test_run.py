from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

import run as lr


def minute_prices(start: str, periods: int = 1440, symbol: str = "BTCUSDT") -> pd.DataFrame:
    minute = pd.date_range(start, periods=periods, freq="min", tz="UTC")
    base = 100.0 + np.arange(periods) * 0.001
    return pd.DataFrame(
        {
            "symbol": symbol,
            "minute": minute,
            "open": base,
            "high": base + 0.2,
            "low": base - 0.2,
            "close": base + 0.05,
            "source_date": minute[0].date().isoformat(),
        }
    )


def liquidation_rows(ts: pd.Timestamp, side: str, amounts: list[float]) -> pd.DataFrame:
    direction = 1 if side == "buy" else -1
    rows = []
    for idx, amount in enumerate(amounts):
        event_time = ts + pd.Timedelta(seconds=idx)
        rows.append(
            {
                "symbol": "BTCUSDT",
                "event_time": event_time,
                "minute": event_time.floor("min"),
                "price": 100.0,
                "amount": amount,
                "notional": 100.0 * amount,
                "force_direction": direction,
                "side": side,
                "row_order": idx,
                "source_date": ts.date().isoformat(),
            }
        )
    return pd.DataFrame(rows)


def test_liquidation_side_semantics() -> None:
    ts = pd.Timestamp("2023-01-01T00:00:10Z")
    rows = pd.concat(
        [liquidation_rows(ts, "buy", [2.0]), liquidation_rows(ts, "sell", [1.0])],
        ignore_index=True,
    )
    agg = lr.aggregate_liquidations(rows)
    assert agg.iloc[0]["buy_notional"] == pytest.approx(200.0)
    assert agg.iloc[0]["sell_notional"] == pytest.approx(100.0)
    # Tardis buy means short liquidation, hence positive forced direction for continuation.
    signed = agg.iloc[0]["buy_notional"] - agg.iloc[0]["sell_notional"]
    assert signed > 0


def test_build_features_enforces_next_bar_entries() -> None:
    day = date(2023, 1, 1)
    prices = minute_prices("2023-01-01T00:00:00Z")
    event_minute = pd.Timestamp("2023-01-01T12:00:00Z")
    liq = liquidation_rows(event_minute + pd.Timedelta(seconds=5), "buy", [10.0])
    features, _ = lr.build_features(liq, prices, [day], ["BTCUSDT"])
    row = features.loc[features["minute"] == event_minute].iloc[0]
    assert row["continuation_entry_time"] == event_minute + pd.Timedelta(minutes=1)
    assert row["reversal_decision_time"] == event_minute + pd.Timedelta(minutes=1)
    assert row["reversal_entry_time"] == event_minute + pd.Timedelta(minutes=2)


def test_feature_prefix_invariance() -> None:
    day = date(2023, 1, 1)
    prices = minute_prices("2023-01-01T00:00:00Z")
    t0 = pd.Timestamp("2023-01-01T12:00:00Z")
    early = liquidation_rows(t0 + pd.Timedelta(seconds=2), "sell", [4.0, 3.0])
    future = liquidation_rows(t0 + pd.Timedelta(hours=2), "buy", [1000.0])
    base, _ = lr.build_features(early, prices, [day], ["BTCUSDT"])
    extended, _ = lr.build_features(pd.concat([early, future]), prices, [day], ["BTCUSDT"])
    columns = [
        "buy_notional",
        "sell_notional",
        "dominant_notional",
        "dominance",
        "acceleration",
        "directional_return_bps",
        "close_location",
    ]
    pd.testing.assert_series_equal(
        base.loc[base["minute"] == t0, columns].iloc[0],
        extended.loc[extended["minute"] == t0, columns].iloc[0],
        check_names=False,
    )


def test_stop_first_when_both_barriers_touch() -> None:
    frame = pd.DataFrame(
        {
            "minute": pd.date_range("2023-01-01T00:00:00Z", periods=3, freq="min"),
            "open": [100.0, 100.0, 100.0],
            "high": [100.1, 103.0, 100.1],
            "low": [99.9, 97.0, 99.9],
            "close": [100.0, 100.0, 100.0],
        }
    )
    series = lr.PriceSeries.from_frame(frame)
    exit_time, exit_price, reason = series.resolve_oco(
        entry_time=pd.Timestamp("2023-01-01T00:01:00Z"),
        path_end=pd.Timestamp("2023-01-02T00:00:00Z"),
        direction=1,
        stop_price=98.0,
        target_price=102.0,
    )
    assert exit_time == pd.Timestamp("2023-01-01T00:01:00Z")
    assert exit_price == 98.0
    assert reason == "stop"


def test_gap_stop_uses_adverse_actual_open() -> None:
    frame = pd.DataFrame(
        {
            "minute": pd.date_range("2023-01-01T00:01:00Z", periods=3, freq="min"),
            "open": [100.0, 95.0, 95.0],
            "high": [100.1, 96.0, 95.1],
            "low": [99.9, 94.0, 94.9],
            "close": [100.0, 95.0, 95.0],
        }
    )
    series = lr.PriceSeries.from_frame(frame)
    exit_time, exit_price, reason = series.resolve_oco(
        entry_time=pd.Timestamp("2023-01-01T00:01:00Z"),
        path_end=pd.Timestamp("2023-01-01T00:04:00Z"),
        direction=1,
        stop_price=98.0,
        target_price=102.0,
    )
    assert exit_time == pd.Timestamp("2023-01-01T00:02:00Z")
    assert exit_price == 95.0
    assert reason == "stop"


def test_price_path_does_not_bridge_missing_minute() -> None:
    frame = pd.DataFrame(
        {
            "minute": pd.to_datetime(
                ["2023-01-01T00:01:00Z", "2023-01-01T00:03:00Z"]
            ),
            "open": [100.0, 100.0],
            "high": [100.1, 103.0],
            "low": [99.9, 99.9],
            "close": [100.0, 102.0],
        }
    )
    series = lr.PriceSeries.from_frame(frame)
    exit_time, exit_price, reason = series.resolve_oco(
        entry_time=pd.Timestamp("2023-01-01T00:01:00Z"),
        path_end=pd.Timestamp("2023-01-01T00:04:00Z"),
        direction=1,
        stop_price=98.0,
        target_price=102.0,
    )
    assert exit_time is None
    assert exit_price is None
    assert reason == "unresolved_source_gap"


def test_risk_sizing_stop_loss_includes_cost() -> None:
    prices = pd.DataFrame(
        {
            "minute": pd.date_range("2023-01-01T00:01:00Z", periods=3, freq="min"),
            "open": [100.0, 100.0, 99.0],
            "high": [100.1, 100.1, 99.1],
            "low": [99.9, 98.0, 98.9],
            "close": [100.0, 99.0, 99.0],
        }
    )
    series = {"BTCUSDT": lr.PriceSeries.from_frame(prices)}
    signals = pd.DataFrame(
        [
            {
                "symbol": "BTCUSDT",
                "family": "continuation",
                "signal_id": "s1",
                "minute": pd.Timestamp("2023-01-01T00:00:00Z"),
                "entry_time": pd.Timestamp("2023-01-01T00:01:00Z"),
                "direction": 1,
                "event_low": 99.0,
                "event_high": 100.5,
                "dominant_notional": 1000.0,
            }
        ]
    )
    candidate = {"min_stop_bps": 8.0, "target_r": 2.0}
    metrics, trades = lr.simulate_account(
        signals,
        candidate,
        series,
        initial_nav=10000.0,
        risk_fraction=0.005,
        cost_bps=18.0,
        calendar_days=365,
        observed_days=1,
    )
    assert metrics["trade_count"] == 1
    assert trades.iloc[0]["exit_reason"] == "stop"
    # Planned stop loss, inclusive of entry and stop costs, is exactly the risk budget.
    assert trades.iloc[0]["pnl"] == pytest.approx(-50.0, rel=1e-9, abs=1e-9)


def test_global_slot_skips_overlapping_signal() -> None:
    prices = pd.DataFrame(
        {
            "minute": pd.date_range("2023-01-01T00:01:00Z", periods=10, freq="min"),
            "open": [100.0] * 10,
            "high": [100.1, 100.1, 100.1, 100.1, 103.0, 100.1, 100.1, 100.1, 100.1, 100.1],
            "low": [99.9] * 10,
            "close": [100.0] * 10,
        }
    )
    series = {"BTCUSDT": lr.PriceSeries.from_frame(prices), "ETHUSDT": lr.PriceSeries.from_frame(prices)}
    signals = pd.DataFrame(
        [
            {
                "symbol": "BTCUSDT",
                "family": "continuation",
                "signal_id": "a",
                "minute": pd.Timestamp("2023-01-01T00:00:00Z"),
                "entry_time": pd.Timestamp("2023-01-01T00:01:00Z"),
                "direction": 1,
                "event_low": 99.0,
                "event_high": 100.5,
                "dominant_notional": 2000.0,
            },
            {
                "symbol": "ETHUSDT",
                "family": "continuation",
                "signal_id": "b",
                "minute": pd.Timestamp("2023-01-01T00:01:00Z"),
                "entry_time": pd.Timestamp("2023-01-01T00:02:00Z"),
                "direction": 1,
                "event_low": 99.0,
                "event_high": 100.5,
                "dominant_notional": 1000.0,
            },
        ]
    )
    metrics, trades = lr.simulate_account(
        signals,
        {"min_stop_bps": 8.0, "target_r": 2.0},
        series,
        initial_nav=10000.0,
        risk_fraction=0.005,
        cost_bps=12.0,
        calendar_days=365,
        observed_days=1,
    )
    assert metrics["trade_count"] == 1
    assert metrics["skipped_global_slot"] == 1
    assert list(trades["signal_id"]) == ["a"]


def test_candidate_count_is_frozen() -> None:
    prereg = {
        "account": {"structural_stop_buffer_bps": 2.0},
        "candidate_grid": {
            "liquidation_quantile": [0.9, 0.95, 0.98],
            "dominance_min": [0.6, 0.75],
            "target_r": [1.0, 1.5, 2.0],
            "min_stop_bps": [8.0, 15.0],
            "continuation": {
                "acceleration_min": [1.5, 3.0],
                "impact_min_bps": [2.0, 6.0],
                "close_location_min": [0.65, 0.8],
            },
            "reversal": {
                "deceleration_max": [0.25, 0.5],
                "recovery_min": [0.35, 0.55],
                "event_move_min_bps": [3.0, 8.0],
            },
        }
    }
    candidates = lr.generate_candidates(prereg)
    assert len(candidates) == 576
    assert len({c["candidate_id"] for c in candidates}) == 576


def test_signal_is_cancelled_when_entry_has_crossed_invalidation() -> None:
    minute = pd.Timestamp("2023-01-01T00:00:00Z")
    features = pd.DataFrame(
        [
            {
                "symbol": "BTCUSDT",
                "minute": minute,
                "force_direction": 1,
                "dominant_notional": 1000.0,
                "dominance": 1.0,
                "acceleration": 10.0,
                "directional_return_bps": 10.0,
                "close_location": 1.0,
                "entry_open_continuation": 98.0,
                "continuation_entry_time": minute + pd.Timedelta(minutes=1),
                "event_high_continuation": 101.0,
                "event_low_continuation": 99.0,
            }
        ]
    )
    candidate = {
        "candidate_id": "x",
        "family": "continuation",
        "liquidation_quantile": 0.9,
        "dominance_min": 0.6,
        "acceleration_min": 1.5,
        "impact_min_bps": 2.0,
        "close_location_min": 0.65,
        "structural_stop_buffer_bps": 2.0,
    }
    selected = lr.select_signals(features, candidate, {0.9: {"BTCUSDT": 500.0}})
    assert selected.empty
