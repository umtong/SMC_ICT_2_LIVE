from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="full alpha-wave tests run in the pinned research workflow")
pd = pytest.importorskip("pandas", reason="full alpha-wave tests run in the pinned research workflow")

MODULE_PATH = Path(__file__).parents[1] / "research" / "alpha_wave1" / "binance_alpha_wave1.py"
if not MODULE_PATH.exists():
    reconstruct_path = MODULE_PATH.with_name("reconstruct_source.py")
    reconstruct_spec = importlib.util.spec_from_file_location("alpha_wave1_reconstruct", reconstruct_path)
    assert reconstruct_spec and reconstruct_spec.loader
    reconstruct = importlib.util.module_from_spec(reconstruct_spec)
    reconstruct_spec.loader.exec_module(reconstruct)
    assert reconstruct.main() == 0

spec = importlib.util.spec_from_file_location("alpha_wave1", MODULE_PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def minute_panel(start="2022-01-01T00:00:00Z", minutes=120, price=100.0):
    idx = pd.date_range(start, periods=minutes, freq="1min", tz="UTC")
    frame = pd.DataFrame(index=idx)
    frame["open"] = price
    frame["high"] = price + 1.0
    frame["low"] = price - 1.0
    frame["close"] = price
    frame["quote_volume"] = 1000.0
    frame["count"] = 10.0
    frame["taker_buy_quote_volume"] = 500.0
    frame["present"] = True
    return frame


def execution(frame, funding=None):
    if funding is None:
        funding = pd.DataFrame(columns=["time", "rate"])
    return m.make_execution_panel(frame, funding)


def signal(time, side=1, stop=95.0, horizon=1, symbol="BTCUSDT", score=1.0):
    return pd.DataFrame(
        [
            {
                "candidate_id": "c",
                "family": "f",
                "signal_time": pd.Timestamp(time),
                "symbol": symbol,
                "side": side,
                "score": score,
                "stop": stop,
                "horizon": horizon,
                "signal_index": 0,
            }
        ]
    )


def test_five_minute_requires_all_source_minutes():
    one = minute_panel(minutes=10)
    one.iloc[2, one.columns.get_loc("present")] = False
    one.iloc[2, one.columns.get_loc("open")] = np.nan
    five = m.build_five_minute(one)
    assert not bool(five.iloc[0].present)
    assert bool(five.iloc[1].present)


def test_prior_high_excludes_current_completed_bar():
    idx = pd.date_range("2022-01-01", periods=400, freq="5min", tz="UTC")
    five = pd.DataFrame(index=idx)
    five["open"] = 100.0
    five["high"] = 101.0
    five["low"] = 99.0
    five["close"] = 100.0
    five["quote_volume"] = 1000.0
    five["taker_buy_quote_volume"] = 500.0
    five["count"] = 10.0
    five["present"] = True
    five["minutes_present"] = 5
    five.iloc[-1, five.columns.get_loc("high")] = 200.0
    feat = m.build_features(five)
    assert feat.iloc[-1]["prior_high_12"] == 101.0


def test_signal_enters_only_after_completed_five_minute_bar():
    one = minute_panel(minutes=30)
    one.loc[pd.Timestamp("2022-01-01T00:10:00Z"), "open"] = 110.0
    one.loc[pd.Timestamp("2022-01-01T00:15:00Z"), "open"] = 111.0
    sig = signal("2022-01-01T00:05:00Z", side=1, stop=90.0, horizon=1)
    ledger = m.run_backtest(sig, {"BTCUSDT": execution(one)}, 0.0)
    assert len(ledger) == 1
    assert ledger.iloc[0].entry_time == pd.Timestamp("2022-01-01T00:10:00Z")
    assert ledger.iloc[0].entry == 110.0
    assert ledger.iloc[0].exit_time == pd.Timestamp("2022-01-01T00:15:00Z")


def test_gap_stop_uses_actual_open_and_extra_cost():
    one = minute_panel(minutes=30)
    one.loc[pd.Timestamp("2022-01-01T00:10:00Z"), "open"] = 100.0
    one.loc[pd.Timestamp("2022-01-01T00:11:00Z"), ["open", "high", "low", "close"]] = [90.0, 91.0, 89.0, 90.0]
    sig = signal("2022-01-01T00:05:00Z", side=1, stop=95.0, horizon=2)
    ledger = m.run_backtest(sig, {"BTCUSDT": execution(one)}, 16.0)
    row = ledger.iloc[0]
    assert row.exit_reason == "gap_stop"
    assert row.exit == 90.0
    expected = np.log(90.0 / 100.0) - 0.0016 - m.STOP_EXTRA_BPS / 1e4
    assert abs(row.net_log - expected) < 1e-12


def test_same_minute_protective_stop_has_adverse_priority():
    one = minute_panel(minutes=30)
    one.loc[pd.Timestamp("2022-01-01T00:10:00Z"), ["open", "high", "low", "close"]] = [100.0, 120.0, 94.0, 110.0]
    sig = signal("2022-01-01T00:05:00Z", side=1, stop=95.0, horizon=1)
    ledger = m.run_backtest(sig, {"BTCUSDT": execution(one)}, 0.0)
    assert ledger.iloc[0].exit_reason == "protective_stop"
    assert ledger.iloc[0].exit == 95.0


def test_global_slot_rejects_overlapping_second_symbol_signal():
    one_b = minute_panel(minutes=60)
    one_e = minute_panel(minutes=60, price=200.0)
    signals = pd.concat(
        [
            signal("2022-01-01T00:05:00Z", side=1, stop=90.0, horizon=4, symbol="BTCUSDT", score=2.0),
            signal("2022-01-01T00:10:00Z", side=1, stop=180.0, horizon=1, symbol="ETHUSDT", score=1.0),
        ],
        ignore_index=True,
    )
    ledger = m.run_backtest(signals, {"BTCUSDT": execution(one_b), "ETHUSDT": execution(one_e)}, 0.0)
    assert len(ledger) == 1
    assert ledger.iloc[0].symbol == "BTCUSDT"


def test_positive_funding_costs_long_and_benefits_short():
    one = minute_panel(minutes=60)
    funding = pd.DataFrame(
        {"time": [pd.Timestamp("2022-01-01T00:12:00Z")], "rate": [0.001]}
    )
    panel = execution(one, funding)
    long_ledger = m.run_backtest(signal("2022-01-01T00:05:00Z", 1, 90.0, 2), {"BTCUSDT": panel}, 0.0)
    short_ledger = m.run_backtest(signal("2022-01-01T00:05:00Z", -1, 110.0, 2), {"BTCUSDT": panel}, 0.0)
    assert abs(long_ledger.iloc[0].funding_log + 0.001) < 1e-12
    assert abs(short_ledger.iloc[0].funding_log - 0.001) < 1e-12


def test_development_gate_requires_positive_median_and_trimmed_growth():
    row = {
        "base_trades": 100,
        "base_log_growth": 1.0,
        "stress_log_growth": 0.5,
        "base_profit_factor": 1.5,
        "base_median_bps": 1.0,
        "base_positive_quarters": 4,
        "base_top10_positive_share": 0.2,
        "base_after_top10_log_growth": 0.2,
        "base_max_drawdown": 0.1,
        "base_max_symbol_share": 0.7,
        "base_max_direction_share": 0.7,
    }
    assert m.development_gate(row)
    row["base_median_bps"] = -0.1
    assert not m.development_gate(row)


def test_candidate_ids_are_unique_and_family_diverse():
    specs = m.candidate_specs()
    assert len(specs) == len({x["candidate_id"] for x in specs})
    assert {x["family"] for x in specs} == {
        "liquidity_sweep_reclaim",
        "liquidity_sweep_acceptance",
        "balance_to_imbalance",
        "displacement_origin_retest",
        "cross_asset_lag",
        "donchian_trend_baseline",
    }


def test_concentration_audit_removes_winners_not_losses():
    ledger = pd.DataFrame(
        {
            "net_log": [0.01, -0.20, -0.10],
            "exit_time": pd.to_datetime(
                ["2022-01-01T01:00:00Z", "2022-01-02T01:00:00Z", "2022-01-03T01:00:00Z"], utc=True
            ),
            "symbol": ["BTCUSDT", "BTCUSDT", "ETHUSDT"],
            "side": [1, -1, 1],
            "exit_reason": ["alpha_horizon"] * 3,
            "funding_log": [0.0] * 3,
        }
    )
    result = m.metrics(ledger, pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2023-01-01", tz="UTC"))
    # Removing the sole winning trade must leave both losses, not delete a loss.
    assert abs(result["after_top10_log_growth"] + 0.30) < 1e-12
    assert abs(result["top1pct_removed_log_growth"] + 0.30) < 1e-12
