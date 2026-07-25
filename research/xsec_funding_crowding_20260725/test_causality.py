from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("research", HERE / "run_research.py")
research = importlib.util.module_from_spec(SPEC)
sys.modules["research"] = research
assert SPEC.loader is not None
SPEC.loader.exec_module(research)


def synthetic_panel() -> pd.DataFrame:
    symbols = [f"S{i}" for i in range(8)]
    rows = []
    for event_time in pd.date_range("2022-01-01", periods=4, freq="8h", tz="UTC"):
        for index, symbol in enumerate(symbols):
            entry = event_time + pd.Timedelta(hours=1)
            rows.append({
                "symbol": symbol,
                "event_time": event_time,
                "calc_time": event_time + pd.Timedelta(milliseconds=50 + index),
                "calc_delay_ms": 50 + index,
                "funding_rate": (index - 3.5) * 1e-4,
                "funding_delta": (index - 3.5) * 1e-5,
                "funding_ts_z": index - 3.5,
                "ret8": (index - 3.5) * 0.001,
                "flow8": (index - 3.5) / 10,
                "prior_quote24": 1e9,
                "feature_time": event_time - pd.Timedelta(hours=1),
                "entry_time": entry,
                "entry_open": 100.0,
                "exit_3h": 100.0 + (index - 3.5) * 0.1,
                "exit_6h": 100.0 + (index - 3.5) * 0.2,
            })
    return pd.DataFrame(rows)


def test_entry_is_after_funding_and_feature_time():
    panel = synthetic_panel()
    assert (panel["entry_time"] > panel["calc_time"]).all()
    assert (panel["entry_time"] > panel["feature_time"]).all()


def test_cross_section_uses_only_same_event():
    config = {"min_prior_24h_quote_volume": 50_000_000, "min_cross_section": 6}
    prepared = research.prepare_cross_section(synthetic_panel(), config)
    assert prepared.groupby("event_time")["cross_section_size"].nunique().eq(1).all()
    assert prepared.groupby("event_time").size().eq(8).all()


def test_candidate_id_is_stable():
    a = research.Candidate("funding_level_reversal", 2, 6, 0.5)
    b = research.Candidate("funding_level_reversal", 2, 6, 0.5)
    assert a.candidate_id == b.candidate_id


def test_future_rows_do_not_change_prior_ledger():
    config = {"min_prior_24h_quote_volume": 50_000_000, "min_cross_section": 6}
    prepared = research.prepare_cross_section(synthetic_panel(), config)
    candidate = research.Candidate("funding_level_continuation", 1, 3, 0.25)
    events_a, _ = research.build_ledger(prepared.iloc[:16].copy(), candidate, 12)
    modified = prepared.copy()
    modified.loc[modified["event_time"] == modified["event_time"].max(), "exit_3h"] *= 100
    events_b, _ = research.build_ledger(modified.iloc[:16].copy(), candidate, 12)
    pd.testing.assert_frame_equal(events_a.reset_index(drop=True), events_b.reset_index(drop=True))


def test_market_neutral_weights():
    config = {"min_prior_24h_quote_volume": 50_000_000, "min_cross_section": 6}
    prepared = research.prepare_cross_section(synthetic_panel(), config)
    candidate = research.Candidate("funding_level_continuation", 2, 3, 0.25)
    events, legs = research.build_ledger(prepared, candidate, 12)
    assert not events.empty
    grouped = legs.groupby(["event_time", "side"])["weight"].sum().unstack()
    assert np.allclose(grouped["LONG"], 0.5)
    assert np.allclose(grouped["SHORT"], 0.5)


if __name__ == "__main__":
    tests = [name for name in globals() if name.startswith("test_")]
    for name in tests:
        globals()[name]()
        print("PASS", name)
