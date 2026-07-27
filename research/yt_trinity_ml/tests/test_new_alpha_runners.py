from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

import harvest_public_frontend_content as content
import run_cisd_bpr_ifvg_research as cisd
import run_compression_bpr_continuation as compression
import run_full_sequential_survivor as full
import run_smt_cisd_research as smt
import select_coarse_survivor as selector


def synthetic_frame(seed: int, scale: float = 1.0, count: int = 900) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2022-01-01T00:05:00Z", periods=count, freq="5min")
    drift = np.sin(np.arange(count) / 37.0) * 0.00025 + 0.00002
    noise = rng.normal(0, 0.0012, count)
    close = 1000.0 * scale * np.exp(np.cumsum(drift + noise))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.maximum(close * rng.uniform(0.0002, 0.0015, count), close * 0.0001)
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.lognormal(6.0, 0.7, count)
    frame = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "turnover": volume * close,
            "mark_close": close,
            "spread_bps": 0.5,
            "bar_start": index - pd.Timedelta(minutes=5),
        },
        index=index,
    )
    frame.index.name = "available_at"
    return frame


def test_three_event_generators_are_causal_and_executable() -> None:
    btc = synthetic_frame(11, 30.0)
    eth = synthetic_frame(17, 2.0)
    cisd_features, cisd_rows = cisd.generate_candidates(btc, "BTCUSDT")
    compression_features, compression_rows = compression.generate_candidates(btc, "BTCUSDT")
    smt_features, smt_rows = smt.generate_joint_candidates({"BTCUSDT": btc, "ETHUSDT": eth})
    assert len(cisd_features) == len(btc)
    assert len(compression_features) == len(btc)
    assert set(smt_features) == {"BTCUSDT", "ETHUSDT"}
    for row in [*cisd_rows, *compression_rows, *smt_rows]:
        assert row.timestamp in btc.index
        assert row.side in {-1, 1}
        assert row.stop_distance > 0
        assert row.target_distance > 0
        assert row.feature_row.get("raw_reward_risk", 0) > 0


def test_frontend_caption_parsers_require_timestamped_text() -> None:
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n안녕하세요\n\n"
    rows = content.parse_caption(vtt.encode(), "text/vtt")
    assert len(rows) == 1 and rows[0].start_ms == 1000 and rows[0].text == "안녕하세요"
    json3 = {
        "events": [
            {"tStartMs": 2500, "dDurationMs": 1200, "segs": [{"utf8": "구조 전환"}]}
        ]
    }
    rows = content.parse_caption(json.dumps(json3, ensure_ascii=False).encode(), "application/json")
    assert len(rows) == 1 and rows[0].start_ms == 2500 and rows[0].text == "구조 전환"
    assert content.parse_caption(b"<html>long error page</html>", "text/html") == []


def test_half_year_summary_preserves_continuous_nav() -> None:
    rows = []
    nav = 10_000.0
    for timestamp in pd.date_range("2024-01-02T00:00:00Z", "2026-07-01T00:00:00Z", freq="1D"):
        nav *= 1.0002
        rows.append(SimpleNamespace(timestamp=timestamp, nav=nav, cash=nav, unrealized_pnl=0.0, symbol=None, quantity=0.0))
    account = SimpleNamespace(daily_nav=rows)
    half_years = full.half_year_summary(account)
    assert len(half_years) == 5
    assert half_years[0]["start_nav"] == 10_000.0
    for previous, current in zip(half_years, half_years[1:]):
        assert abs(previous["end_nav"] - current["start_nav"]) < 1e-9
    assert half_years[-1]["end_exclusive"] == "2026-07-01T00:00:00+00:00"


def test_survivor_selector_uses_pre2024_magnitude(tmp_path: Path) -> None:
    route_payloads = {
        "CISD_BPR_IFVG_RUN_POINTER.json": (0.002, 0.0001),
        "COMPRESSION_BPR_RUN_POINTER.json": (0.001, 0.02),
        "SMT_CISD_RUN_POINTER.json": (-0.001, 0.0),
    }
    for filename, (pre_growth, h1_growth) in route_payloads.items():
        positive = pre_growth > 0
        payload = {
            "run_id": 1,
            "source_sha": "a" * 40,
            "decision": "POSITIVE_PRE2024_OPENED_2024H1_COARSE" if positive else "ECONOMIC_FAIL_SWITCH_ALPHA",
            "selected_basic": {
                "variant_set": "ALL_CAUSAL_ZONES",
                "model_spec": {
                    "name": "MEDIUM",
                    "max_leaf_nodes": 15,
                    "min_samples_leaf": 35,
                    "l2_regularization": 1.5,
                    "confidence_penalty": 0.35,
                    "update_cadence_days": 28,
                    "activation_lag_minutes": 15,
                },
                "metrics": {
                    "geometric_daily_growth": pre_growth,
                    "account_multiple": 1.2 if positive else 0.8,
                    "maximum_drawdown": 0.1,
                    "completed_trades": 100,
                    "liquidated_or_invalid": False,
                },
            },
            "selected_risk": {"risk_fraction": 0.01, "maximum_leverage": 5.0},
            "official_2024h1": {
                "metrics": {
                    "geometric_daily_growth": h1_growth,
                    "account_multiple": 1.1 if h1_growth > 0 else 1.0,
                    "maximum_drawdown": 0.2,
                    "completed_trades": 50,
                    "liquidated_or_invalid": False,
                }
            },
        }
        (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "selected.json"
    import sys
    original = sys.argv
    try:
        sys.argv = ["select", "--root", str(tmp_path), "--output", str(output)]
        selector.main()
    finally:
        sys.argv = original
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["decision"] == "POSITIVE_H1_FULL_SEQUENTIAL_REQUIRED"
    assert result["selected"]["route_key"] == "cisd_bpr_ifvg"
