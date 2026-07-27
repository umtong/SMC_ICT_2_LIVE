from __future__ import annotations

from dataclasses import replace

import pandas as pd

import run_public_trade_tape_validation as tape


def mark_frame() -> pd.DataFrame:
    starts = pd.date_range("2024-01-01T00:00:00Z", periods=12, freq="1min")
    return pd.DataFrame(
        {
            "bar_start": starts,
            "open": 100.0,
            "high": 106.0,
            "low": 97.0,
            "close": 101.0,
            "mark_close": 101.0,
        },
        index=starts + pd.Timedelta(minutes=1),
    )


def signal(action: str = "PASSIVE_RETEST") -> tape.FrozenSignal:
    return tape.FrozenSignal(
        timestamp=pd.Timestamp("2024-01-01T00:00:00Z"),
        symbol="BTCUSDT",
        family="TEST",
        side=1,
        decision_price=100.0,
        entry_reference=99.0,
        stop_reference=97.0,
        target_reference=105.0,
        structural_level=98.0,
        feature_row={},
        lower_confidence_score=0.01,
        expected_log_growth=0.01,
        expected_net_r=1.0,
        win_probability=0.6,
        chosen_action=action,
    )


def test_normalization_preserves_file_order_at_equal_timestamp() -> None:
    raw = pd.DataFrame(
        {
            "timestamp": [1704067200.5, 1704067200.5, 1704067200.6],
            "symbol": ["BTCUSDT"] * 3,
            "side": ["Sell", "Buy", "Buy"],
            "size": [1.0, 2.0, 3.0],
            "price": [99.0, 100.0, 101.0],
            "trdMatchID": ["z", "a", "m"],
        }
    )
    normalized = tape.normalize_trade_frame(raw, "BTCUSDT", pd.Timestamp("2024-01-01T00:00:00Z"))
    assert normalized["price"].tolist() == [99.0, 100.0, 101.0]


def test_passive_touch_is_not_fill_and_trade_through_can_partially_fill() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2024-01-01T00:00:00.500Z",
                    "2024-01-01T00:00:00.600Z",
                    "2024-01-01T00:00:00.700Z",
                    "2024-01-01T00:00:01.000Z",
                    "2024-01-01T00:00:01.100Z",
                ]
            ),
            "price": [99.0, 98.9, 98.9, 105.1, 105.1],
            "size": [100.0, 2.5, 2.5, 2.0, 3.0],
            "side": ["sell", "sell", "sell", "buy", "buy"],
            "sequence": ["1", "2", "3", "4", "5"],
            "row_order": range(5),
        }
    )
    frame["timestamp_ns"] = pd.DatetimeIndex(frame["timestamp"]).as_unit("ns").asi8

    class Archive:
        download_ledger = []
        def get(self, symbol, day):
            return frame

    config = tape.TapeConfig(
        activation_latency_ms=500,
        maker_fee_rate=0.0,
        taker_fee_rate=0.0,
        minimum_spread_bps=0.0,
        market_slippage_bps=0.0,
        stop_slippage_bps=0.0,
        passive_entry_queue_multiple=0.5,
        passive_target_queue_multiple=0.5,
        base_impact_bps=0.0,
        impact_bps_per_sqrt_participation=0.0,
        maximum_impact_bps=0.0,
    )
    result = tape.resolve_signal(
        signal(),
        requested_quantity=5.0,
        starting_cash=10_000.0,
        archive=Archive(),
        funding={},
        mark_frame=mark_frame(),
        config=config,
    )
    entry_fills = [row for row in result["fill_events"] if row.role == "ENTRY"]
    target_fills = [row for row in result["fill_events"] if row.role == "TARGET"]
    assert result["status"] == "TARGET"
    assert entry_fills
    assert sum(row.quantity for row in entry_fills) == 2.5
    assert sum(row.quantity for row in target_fills) == 2.5
    assert entry_fills[0].timestamp > pd.Timestamp("2024-01-01T00:00:00.500Z")


def test_market_order_obeys_500ms_and_latency_geometry() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2024-01-01T00:00:00.400Z", "2024-01-01T00:00:00.500Z"]
            ),
            "price": [100.0, 106.0],
            "size": [100.0, 100.0],
            "side": ["buy", "buy"],
            "sequence": ["1", "2"],
            "row_order": [0, 1],
        }
    )
    frame["timestamp_ns"] = pd.DatetimeIndex(frame["timestamp"]).as_unit("ns").asi8

    class Archive:
        download_ledger = []
        def get(self, symbol, day):
            return frame

    config = tape.TapeConfig(
        activation_latency_ms=500,
        maker_fee_rate=0.0,
        taker_fee_rate=0.0,
        minimum_spread_bps=0.0,
        market_slippage_bps=0.0,
        stop_slippage_bps=0.0,
        base_impact_bps=0.0,
        impact_bps_per_sqrt_participation=0.0,
        maximum_impact_bps=0.0,
    )
    result = tape.resolve_signal(
        signal("MARKETABLE"),
        requested_quantity=1.0,
        starting_cash=10_000.0,
        archive=Archive(),
        funding={},
        mark_frame=mark_frame(),
        config=config,
    )
    assert result["status"] == "CANCELLED_LATENCY_GEOMETRY"
    assert not result["fill_events"]


def test_day_interaction_index_skips_irrelevant_intermediate_days() -> None:
    bars = mark_frame().copy()
    bars["high"] = 102.0
    bars["low"] = 99.5
    assert not tape.day_requires_trade_archive(
        signal(),
        pd.Timestamp("2024-01-01T00:00:00Z"),
        pd.Timestamp("2024-01-01T00:00:00.500Z"),
        bars,
        entry_filled=0.0,
        open_quantity=0.0,
    )
    bars.loc[bars.index[0], "low"] = 98.8
    assert tape.day_requires_trade_archive(
        signal(),
        pd.Timestamp("2024-01-01T00:00:00Z"),
        pd.Timestamp("2024-01-01T00:00:00.500Z"),
        bars,
        entry_filled=0.0,
        open_quantity=0.0,
    )
