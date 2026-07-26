from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import run_model as m


def minute_frame(hours: int = 8) -> pd.DataFrame:
    index = pd.date_range("2021-01-01", periods=hours * 60, freq="1min", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": 100.0,
            "high": 104.0,
            "low": 96.0,
            "close": 100.0,
            "volume": 1000.0,
            "valid": True,
            "quote_turnover": 100_000.0,
            "close_time": index + pd.Timedelta(minutes=1),
        },
        index=index,
    )
    frame.loc[index[2 * 60 : 3 * 60], "high"] = 110.0
    frame.loc[index[2 * 60 : 3 * 60], "low"] = 90.0
    frame.loc[index[5 * 60 + 10], "high"] = 111.0
    return frame


def test_precomputed_pools_are_causal_and_consumed() -> None:
    market = m.build_market_data(minute_frame())
    before = market.frame.loc[pd.Timestamp("2021-01-01T04:59:00Z")]
    at_confirmation = market.frame.loc[pd.Timestamp("2021-01-01T05:00:00Z")]
    after_touch = market.frame.loc[pd.Timestamp("2021-01-01T05:11:00Z")]
    assert np.isnan(before["active_upper_pool"])
    assert at_confirmation["active_upper_pool"] == pytest.approx(110.0)
    assert at_confirmation["active_lower_pool"] == pytest.approx(90.0)
    assert np.isnan(after_touch["active_upper_pool"])
    assert after_touch["active_lower_pool"] == pytest.approx(90.0)


def test_source_failure_never_opens_market(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "SOURCE_GATE_RESULT.json").write_text(
        json.dumps(
            {
                "claim_id": m.CLAIM_ID,
                "status": "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE",
                "conditional_model_screen_authorized": False,
                "market_outcome_opened": False,
                "model_fit": False,
                "trade_or_pnl_opened": False,
                "official_2024_2026_opened": False,
                "orders_submitted": False,
            }
        )
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("market data must remain sealed")

    monkeypatch.setattr(m, "load_market_set", forbidden)
    result = m.run_pipeline(source, tmp_path / "cache", tmp_path / "out")
    assert result["status"] == "SOURCE_GATE_BELOW_GATE"
    assert result["official_2024H1_opened"] is False


def test_fixed_model_and_ev_route() -> None:
    rng = np.random.default_rng(123)
    train = pd.DataFrame(rng.normal(size=(160, len(m.FEATURE_COLUMNS))), columns=m.FEATURE_COLUMNS)
    train["label"] = np.r_[np.zeros(80), np.ones(80)]
    calibration = pd.DataFrame(
        rng.normal(size=(80, len(m.FEATURE_COLUMNS))), columns=m.FEATURE_COLUMNS
    )
    calibration["label"] = np.r_[np.zeros(40), np.ones(40)]
    bundle = m.fit_model_bundle(train, calibration)
    p = m.predict_probability(bundle, calibration)
    assert len(p) == 80
    assert np.all((p >= 0) & (p <= 1))

    rows = pd.DataFrame(
        {
            "upper_pool_distance_bps": [100.0, 100.0],
            "lower_pool_distance_bps": [100.0, 100.0],
        }
    )
    scored = m.score_rows(rows, np.array([0.9, 0.1]), 24.0)
    assert scored["side"].tolist() == [1, -1]
    assert scored["action"].tolist() == ["TRADE", "TRADE"]


def test_unresolved_path_is_structural_stop_not_time_exit() -> None:
    market = m.synthetic_market(minutes=60 * 24 * 20)
    frame = market.frame
    entry_i = 1000
    row = pd.Series(
        {
            "first_touch": "UNRESOLVED",
            "upper_price": float(frame["open"].iloc[entry_i]) * 1.02,
            "lower_price": float(frame["open"].iloc[entry_i]) * 0.98,
            "touch_index": entry_i + 5,
        }
    )
    outcome = m.outcome_for_side(row, 1, frame)
    assert outcome["exit_reason"] == "SOURCE_BOUNDARY_STOP"
    assert "TIME" not in outcome["exit_reason"]


def test_json_serialization_rejects_nonstandard_nan(tmp_path: Path) -> None:
    path = tmp_path / "value.json"
    m.write_json_file(path, {"inf": float("inf"), "nan": float("nan"), "x": np.int64(3)})
    payload = json.loads(path.read_text())
    assert payload == {"inf": None, "nan": None, "x": 3}
