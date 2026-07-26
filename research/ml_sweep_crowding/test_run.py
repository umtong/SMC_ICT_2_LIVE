from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
common = import_module("research.ml_sweep_crowding.common")
strategy = import_module("research.ml_sweep_crowding.strategy")
account = import_module("research.ml_sweep_crowding.account")
runner = SimpleNamespace(
    MarketData=common.MarketData,
    StageSpec=common.StageSpec,
    next_observable_minute=strategy.next_observable_minute,
    resolve_candidate=strategy.resolve_candidate,
    build_global_sequence=strategy.build_global_sequence,
    funding_between=strategy.funding_between,
    effective_entry=account.effective_entry,
    effective_exit=account.effective_exit,
)


def market_from_rows(rows: list[tuple[float, float, float, float]], start: str = "2024-01-01"):
    index = pd.date_range(start, periods=len(rows), freq="1min", tz="UTC")
    one = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    one["volume"] = 1.0
    funding_cum = pd.Series(0.0, index=index)
    return runner.MarketData(
        symbol="BTCUSDT",
        one_minute=one,
        five_minute=pd.DataFrame(),
        funding=pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC")),
        funding_long_cum=funding_cum,
        minute_open=one.open.to_numpy(),
        minute_high=one.high.to_numpy(),
        minute_low=one.low.to_numpy(),
        minute_close=one.close.to_numpy(),
        coverage=1.0,
        one_minute_sha256="x",
        metrics_sha256="y",
        funding_sha256="z",
    )


def test_latency_uses_next_observable_minute():
    decision = pd.Timestamp("2024-01-01T00:05:00Z")
    assert runner.next_observable_minute(decision, 500) == pd.Timestamp("2024-01-01T00:06:00Z")


def test_same_minute_target_and_stop_resolves_stop_first():
    market = market_from_rows([(100, 106, 94, 100)])
    result = runner.resolve_candidate(
        market,
        pd.Timestamp("2024-01-01T00:00:00Z"),
        stop_raw=95,
        target_raw=105,
        direction=1,
    )
    assert result["resolution"] == "stop"
    assert result["exit_raw"] == 95


def test_gap_through_stop_uses_adverse_open():
    market = market_from_rows([(90, 92, 88, 91)])
    result = runner.resolve_candidate(
        market,
        pd.Timestamp("2024-01-01T00:00:00Z"),
        stop_raw=95,
        target_raw=110,
        direction=1,
    )
    assert result["resolution"] == "stop"
    assert result["exit_raw"] == 90


def test_execution_cost_is_adverse_for_both_sides():
    long_entry = runner.effective_entry(100.0, 1, 24.0)
    long_exit = runner.effective_exit(100.0, 1, 24.0)
    short_entry = runner.effective_entry(100.0, -1, 24.0)
    short_exit = runner.effective_exit(100.0, -1, 24.0)
    assert long_entry > 100 > long_exit
    assert short_entry < 100 < short_exit
    assert np.isclose((long_entry - long_exit), (short_exit - short_entry))


def test_global_slot_rejects_same_or_pre_exit_entries():
    stage = runner.StageSpec(
        "test",
        pd.Timestamp("2024-01-01T00:00:00Z"),
        pd.Timestamp("2024-01-02T00:00:00Z"),
        1,
    )
    frame = pd.DataFrame(
        {
            "entry_ts": pd.to_datetime(
                ["2024-01-01T01:00:00Z", "2024-01-01T01:00:00Z", "2024-01-01T02:00:00Z"],
                utc=True,
            ),
            "exit_ts_full": pd.to_datetime(
                ["2024-01-01T02:00:00Z", "2024-01-01T01:30:00Z", "2024-01-01T03:00:00Z"],
                utc=True,
            ),
            "probability": [0.9, 0.8, 0.7],
        }
    )
    sequence = runner.build_global_sequence(frame, stage)
    assert len(sequence) == 1
    assert sequence.iloc[0].probability == 0.9


def test_funding_at_entry_excluded_and_at_exit_included():
    market = market_from_rows([(100, 100, 100, 100)] * 3)
    market.funding_long_cum.iloc[:] = [5.0, 12.0, 20.0]
    value = runner.funding_between(
        market,
        pd.Timestamp("2024-01-01T00:00:00Z"),
        pd.Timestamp("2024-01-01T00:01:00Z"),
        direction=1,
    )
    assert value == 7.0
    assert runner.funding_between(
        market,
        pd.Timestamp("2024-01-01T00:00:00Z"),
        pd.Timestamp("2024-01-01T00:01:00Z"),
        direction=-1,
    ) == -7.0
