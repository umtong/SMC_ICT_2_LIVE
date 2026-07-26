from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("funding_transfer_tardis_sparse", ROOT / "run_tardis_sparse_screen.py")
assert SPEC is not None and SPEC.loader is not None
screen = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = screen
SPEC.loader.exec_module(screen)


def synthetic_day() -> pd.DataFrame:
    base = screen.date_start_us("2022-01-01")
    count = 24 * 60
    local = base + np.arange(count, dtype=np.int64) * 60_000_000 + 100_000
    price = 100.0 + 0.001 * np.arange(count) + 0.2 * np.sin(np.arange(count) / 20)
    funding_timestamp = np.where(
        local < base + 8 * 60 * 60 * 1_000_000,
        base,
        np.where(
            local < base + 16 * 60 * 60 * 1_000_000,
            base + 8 * 60 * 60 * 1_000_000,
            base + 16 * 60 * 60 * 1_000_000,
        ),
    )
    funding_rate = np.where(funding_timestamp < base + 16 * 60 * 60 * 1_000_000, 0.001, -0.001)
    return pd.DataFrame(
        {
            "exchange": "bybit",
            "symbol": "BTCUSDT",
            "timestamp": local - 50_000,
            "local_timestamp": local,
            "funding_timestamp": funding_timestamp,
            "funding_rate": funding_rate,
            "last_price": price,
            "index_price": price * 0.9999,
            "mark_price": price,
        }
    )


def test_url_guard_rejects_later_periods() -> None:
    assert "/2023/12/01/" in screen.source_url("2023-12-01", "BTCUSDT")
    with pytest.raises(AssertionError):
        screen.source_url("2024-01-01", "BTCUSDT")


def test_first_price_requires_one_second_freshness() -> None:
    base = screen.date_start_us("2022-01-01")
    timestamps = np.array([base + 100_000, base + 2_000_000], dtype=np.int64)
    prices = np.array([100.0, 101.0])
    price, observed = screen.first_price_at_or_after(timestamps, prices, base)
    assert price == 100.0
    assert observed == base + 100_000
    missing, missing_time = screen.first_price_at_or_after(timestamps, prices, base + 500_000)
    assert np.isnan(missing)
    assert missing_time is None


def test_event_reconstruction_skips_midnight_and_waits_extra_bar() -> None:
    frame = synthetic_day()
    bars = screen.build_bars(frame)
    events, settlements = screen.event_rows_from_source(frame, bars, "BTCUSDT", "2022-01-01", "fit")
    assert settlements == 2
    assert len(events) == 4
    assert set(events["confirm_bars"]) == {1, 2}
    settlement = screen.date_start_us("2022-01-01") + 8 * 60 * 60 * 1_000_000
    one = events[(events["settlement_ms"] == settlement // 1000) & (events["confirm_bars"] == 1)].iloc[0]
    two = events[(events["settlement_ms"] == settlement // 1000) & (events["confirm_bars"] == 2)].iloc[0]
    assert one["entry_ms"] == (settlement + 10 * 60 * 1_000_000) // 1000
    assert two["entry_ms"] == (settlement + 15 * 60 * 1_000_000) // 1000
    assert bool(one["execution_valid_15"])


def test_scientific_grid_is_unchanged() -> None:
    candidates = screen.ENGINE.generate_candidates()
    assert len(candidates) == 720
    assert len({candidate.candidate_id for candidate in candidates}) == 720
    assert screen.DEPENDENCY_FINGERPRINT == "ac4a68536463e12dc0fb897da7eca685964bf3f201a1c7cb8f71e8bb1be0db97"
