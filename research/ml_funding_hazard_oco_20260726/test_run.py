from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("funding_hazard_run", ROOT / "run.py")
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_prohibited_year_is_blocked() -> None:
    try:
        mod._dataset_url(2024, 1, "BTCUSDT")
    except ValueError:
        pass
    else:
        raise AssertionError("2024 source URL was not blocked")


def test_read_source_uses_local_availability_and_preserves_capture_order(tmp_path: Path) -> None:
    path = tmp_path / "source.csv.gz"
    rows = pd.DataFrame(
        [
            {
                "exchange": "bybit",
                "symbol": "BTCUSDT",
                "timestamp": 2_000_000,
                "local_timestamp": 1_000_000,
                "funding_timestamp": 8_000_000,
                "funding_rate": 0.0001,
                "predicted_funding_rate": 0.0001,
                "open_interest": 10.0,
                "last_price": 100.0,
                "index_price": 100.0,
                "mark_price": 100.0,
            },
            {
                "exchange": "bybit",
                "symbol": "BTCUSDT",
                "timestamp": 1_000_000,
                "local_timestamp": 2_000_000,
                "funding_timestamp": 8_000_000,
                "funding_rate": 0.0001,
                "predicted_funding_rate": 0.0001,
                "open_interest": 10.0,
                "last_price": 101.0,
                "index_price": 101.0,
                "mark_price": 101.0,
            },
        ]
    )
    rows.to_csv(path, index=False, compression="gzip")
    observed = mod.read_source(path)
    assert observed["_seq"].tolist() == [0, 1]
    assert observed["availability_ms"].tolist() == [1_000, 2_000]
    assert observed["exchange_timestamp_ms"].tolist() == [2_000, 1_000]
    assert observed["last_price"].tolist() == [100.0, 101.0]


def test_target_path_and_cost_monotonicity() -> None:
    times = np.arange(0, 20_000, 100, dtype=np.int64)
    prices = np.full(times.shape, 100.0, dtype=float)
    prices[times >= 2_000] = 100.2
    prices[times >= 5_000] = 101.0
    out = mod.simulate_oco(times, prices, 1_000, 10.0, 50.0, 20.0, {})
    assert out.outcome == "TARGET"
    net12 = out.gross_bps - 12 * out.round_trips
    net18 = out.gross_bps - 18 * out.round_trips
    net24 = out.gross_bps - 24 * out.round_trips
    assert net12 > net18 > net24


def test_short_linear_contract_pnl_is_entry_notional_symmetric() -> None:
    times = np.array([1_000, 2_000, 5_000], dtype=np.int64)
    prices = np.array([100.0, 99.8, 99.0], dtype=float)
    out = mod.simulate_oco(times, prices, 1_000, 10.0, 50.0, 20.0, {})
    assert out.outcome == "TARGET"
    assert out.direction == -1
    assert abs(out.gross_bps - 50.0) < 1e-9


def test_no_trigger_occupies_pending_slot_without_cost() -> None:
    times = np.arange(0, 40 * 60 * 1_000, 1_000, dtype=np.int64)
    prices = np.full(times.shape, 100.0, dtype=float)
    out = mod.simulate_oco(times, prices, 1_000, 10.0, 50.0, 20.0, {})
    assert out.outcome == "NO_TRIGGER"
    assert out.round_trips == 0
    assert out.gross_bps == 0
    assert out.exit_ms == 1_000 + mod.PENDING_EXPIRY_MS


def test_cancel_race_is_adverse_double() -> None:
    times = np.array([1_000, 2_000, 2_500, 3_000], dtype=np.int64)
    prices = np.array([100.0, 100.2, 99.8, 100.0], dtype=float)
    out = mod.simulate_oco(times, prices, 1_000, 10.0, 100.0, 100.0, {})
    assert out.outcome == "CANCEL_RACE_DOUBLE"
    assert out.round_trips == 2
    assert out.gross_bps < 0


def test_global_slot_chooses_highest_ev_and_skips_overlap() -> None:
    frame = pd.DataFrame(
        [
            {"activation_ms": 1_000, "event_end_ms": 10_000, "predicted_ev_bps": 9.0, "symbol": "BTCUSDT", "arm": True},
            {"activation_ms": 1_000, "event_end_ms": 2_000, "predicted_ev_bps": 11.0, "symbol": "ETHUSDT", "arm": True},
            {"activation_ms": 1_500, "event_end_ms": 3_000, "predicted_ev_bps": 20.0, "symbol": "BTCUSDT", "arm": True},
            {"activation_ms": 2_500, "event_end_ms": 3_000, "predicted_ev_bps": 8.0, "symbol": "BTCUSDT", "arm": True},
        ]
    )
    selected = mod.global_arbitrate(frame)
    assert selected["symbol"].tolist() == ["ETHUSDT", "BTCUSDT"]
    assert selected["activation_ms"].tolist() == [1_000, 2_500]
