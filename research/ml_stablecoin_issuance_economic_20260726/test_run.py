from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import run as m


def minute_frame(start: str, periods: int = 300, base: float = 100.0) -> pd.DataFrame:
    times = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    x = np.arange(periods)
    close = base + 0.01 * x + 0.5 * np.sin(x / 7)
    return pd.DataFrame({
        "open_time_ms": times.view("int64") // 1_000_000,
        "open": close,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "quote_volume": np.full(periods, 1e6),
    })


def test_utc_timestamp_accepts_aware_and_naive() -> None:
    assert str(m.utc_ts("2022-01-01")) == "2022-01-01 00:00:00+00:00"
    assert str(m.utc_ts("2022-01-01T00:00:00+00:00")) == "2022-01-01 00:00:00+00:00"


def test_label_boundary_is_partition_local() -> None:
    assert m.label_boundary_ms(int(m.utc_ts("2021-12-31T23:00:00Z").timestamp() * 1000)) == int(m.utc_ts("2022-01-01").timestamp() * 1000)
    assert m.label_boundary_ms(int(m.utc_ts("2022-06-30T23:00:00Z").timestamp() * 1000)) == int(m.utc_ts("2022-07-01").timestamp() * 1000)
    assert m.label_boundary_ms(int(m.utc_ts("2022-12-31T23:00:00Z").timestamp() * 1000)) == int(m.utc_ts("2023-01-01").timestamp() * 1000)
    with pytest.raises(AssertionError):
        m.label_boundary_ms(int(m.utc_ts("2024-01-01").timestamp() * 1000))


def test_feature_range_uses_only_prior_minutes() -> None:
    frame = minute_frame("2021-01-01", 100)
    f = m._returns_features(frame)
    assert np.isnan(f["prior_high"][59])
    assert f["prior_high"][60] == pytest.approx(frame.iloc[:60]["high"].max())
    mutated = frame.copy()
    mutated.loc[61:, "high"] = 999999.0
    fm = m._returns_features(mutated)
    assert fm["prior_high"][60] == pytest.approx(f["prior_high"][60])


def test_cost_and_risk_are_adverse_monotone() -> None:
    t = m.Trade(
        event_id="e", symbol="BTCUSDT", decision_ms=1, entry_ms=2, exit_ms=3,
        side=1, entry=100.0, exit_price=99.0, stop_price=99.0, target_price=101.0,
        stop_fraction=0.01, gross_fraction=-0.01, funding_fraction=0.0,
        model_probability_up=0.5, ev_bps=1.0, exit_reason="STOP", ambiguous=False,
    )
    low_cost = m.replay([t], 12, "2021-01-01", "2021-01-02", 0.005, 3)
    high_cost = m.replay([t], 24, "2021-01-01", "2021-01-02", 0.005, 3)
    high_risk = m.replay([t], 24, "2021-01-01", "2021-01-02", 0.01, 3)
    assert high_cost["total_return"] <= low_cost["total_return"]
    assert high_risk["total_return"] <= high_cost["total_return"]


def test_global_slot_uses_one_candidate_per_decision() -> None:
    frame = minute_frame("2021-01-01", 180)
    funding = pd.DataFrame({"time_ms": [], "rate": []})
    row = {
        "event_id": "e1", "symbol": "BTCUSDT", "decision_ms": int(frame.iloc[70]["open_time_ms"]),
        "entry_index": 71, "entry_ms": int(frame.iloc[71]["open_time_ms"]), "exit_index": 80,
        "entry": 100.0, "upper": 101.0, "lower": 99.0,
        "distance_to_frozen_upper_60m_liquidity": 0.01,
        "distance_to_frozen_lower_60m_liquidity": 0.01,
    }
    rows = pd.DataFrame([row, {**row, "symbol": "ETHUSDT"}])
    bars = {"BTCUSDT": frame.copy(), "ETHUSDT": frame.copy()}
    funds = {"BTCUSDT": funding.copy(), "ETHUSDT": funding.copy()}
    trades = m.route(rows, np.array([0.95, 0.95]), bars, funds, 12)
    assert len(trades) == 1


def test_pre2024_event_loader_rejects_missing_columns(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text('{"event_id":"e"}\n')
    with pytest.raises(ValueError):
        m.load_events(p)


def test_self_test() -> None:
    m.self_test()
