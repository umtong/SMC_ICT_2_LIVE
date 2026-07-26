from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT))

from system.core import (  # noqa: E402
    EventCandidate,
    EventFamily,
    FeatureConfig,
    RiskConfig,
    build_causal_features,
    generate_event_candidates,
    size_position_from_nav,
)
from system.model import ScoredCandidate  # noqa: E402
from system.policy import GlobalSlotPolicy, PolicyDecision  # noqa: E402


def bars(count: int = 500) -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=count, freq="5min", tz="UTC")
    rng = np.random.default_rng(7)
    returns = rng.normal(0, 0.0015, count)
    close = 20000 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.maximum(close * rng.uniform(0.0004, 0.002, count), 1)
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.lognormal(5, 0.5, count)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index)


def test_features_do_not_change_when_future_is_appended() -> None:
    frame = bars(500)
    short = build_causal_features(frame.iloc[:400])
    long = build_causal_features(frame)
    pd.testing.assert_frame_equal(short, long.loc[short.index], check_dtype=False)


def test_confirmed_pivot_appears_only_after_right_bars() -> None:
    index = pd.date_range("2023-01-01", periods=15, freq="5min", tz="UTC")
    high = np.array([1, 2, 3, 10, 4, 3, 2, 3, 4, 5, 4, 3, 2, 1, 1], dtype=float) + 100
    low = high - 2
    close = high - 1
    frame = pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": 1.0}, index=index)
    features = build_causal_features(frame, FeatureConfig(atr_window=2, fast_ema=2, slow_ema=3, long_ema=4, volume_window=2, pivot_left=3, pivot_right=3))
    assert np.isnan(features.iloc[5]["confirmed_pivot_high"])
    assert features.iloc[6]["confirmed_pivot_high"] == high[3]


def test_position_size_respects_loss_budget_and_step() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01", tz="UTC"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100.0, 100.0, 98.0, 106.0, 99.0, {})
    quantity = size_position_from_nav(10000, event, RiskConfig(0.02, 10.0, 0.001), 0.00055, 0.00055, 0.0002, 0.0004)
    per_unit = 2 + 100 * (0.00055 + 0.0002) + 98 * (0.00055 + 0.0004)
    assert quantity > 0 and quantity * per_unit <= 200 + 1e-9
    assert abs(quantity * 1000 - round(quantity * 1000)) < 1e-9


def test_global_slot_policy_abstains_and_ranks() -> None:
    event_a = EventCandidate(pd.Timestamp("2023-01-01", tz="UTC"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 99, 103, 99.5, {})
    event_b = EventCandidate(pd.Timestamp("2023-01-01", tz="UTC"), "ETHUSDT", EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION, -1, 100, 100, 102, 96, 101, {})
    a = ScoredCandidate(event_a, 0.6, 0.3, 0.7, 0.01, 0.005)
    b = ScoredCandidate(event_b, 0.7, 0.5, 0.3, 0.02, 0.009)
    policy = GlobalSlotPolicy(0.55)
    assert policy.choose([a, b], slot_available=False).action == PolicyDecision.ABSTAIN
    selected = policy.choose([a, b], slot_available=True)
    assert selected.scored == b and selected.action == PolicyDecision.MARKETABLE


from system.execution import AccountState, ExecutionConfig, ExecutionEngine, ExitReason  # noqa: E402
from system.labels import label_first_passage  # noqa: E402


def simple_tape(index: pd.DatetimeIndex, last: list[float]) -> pd.DataFrame:
    values = np.asarray(last, dtype=float)
    return pd.DataFrame(
        {
            "bid": values - 0.01,
            "ask": values + 0.01,
            "last": values,
            "mark": values,
            "trade_volume": 100.0,
            "bid_size": 1000.0,
            "ask_size": 1000.0,
            "aggressor_side": -1.0,
        },
        index=index,
    )


def test_marketable_entry_obeys_500ms_latency() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 104, 99, {})
    account = AccountState(10000)
    engine = ExecutionEngine(ExecutionConfig(activation_latency_ms=500, base_slippage_bps=0, impact_bps_per_one_percent_depth=0))
    engine.submit_entry(account, event, PolicyDecision.MARKETABLE, 1.0)
    index = pd.to_datetime(["2023-01-01T00:00:00.400Z", "2023-01-01T00:00:00.500Z"])
    tape = simple_tape(index, [100, 101])
    engine.process_entry_row(account, index[0], tape.iloc[0])
    assert account.position is None
    engine.process_entry_row(account, index[1], tape.iloc[1])
    assert account.position is not None and account.position.average_entry_price == 101.01


def test_passive_touch_does_not_imply_full_fill() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION, 1, 101, 100, 98, 105, 99, {})
    account = AccountState(10000)
    engine = ExecutionEngine(ExecutionConfig(activation_latency_ms=0, passive_queue_multiple=0.01, passive_through_fraction_at_touch=0.0))
    engine.submit_entry(account, event, PolicyDecision.PASSIVE_RETEST, 1.0)
    index = pd.to_datetime(["2023-01-01T00:00:00Z", "2023-01-01T00:00:01Z"])
    tape = simple_tape(index, [100.0, 99.9])
    engine.process_entry_row(account, index[0], tape.iloc[0])
    assert account.position is None
    engine.process_entry_row(account, index[1], tape.iloc[1])
    assert account.position is not None and account.position.quantity == 1.0


def test_same_timestamp_barrier_collision_is_stop_first() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 102, 99, {})
    account = AccountState(10000)
    engine = ExecutionEngine(ExecutionConfig(activation_latency_ms=0, base_slippage_bps=0, impact_bps_per_one_percent_depth=0))
    engine.submit_entry(account, event, PolicyDecision.MARKETABLE, 1.0)
    index = pd.to_datetime(["2023-01-01T00:00:00Z", "2023-01-01T00:00:01Z"])
    tape = simple_tape(index, [100, 102])
    engine.process_entry_row(account, index[0], tape.iloc[0])
    collision = tape.iloc[1].copy()
    collision["mark"] = 97.9
    collision["last"] = 102.1
    engine.process_position_row(account, index[1], collision)
    assert account.position is None and account.fills[-1].role == ExitReason.STOP.value


def test_no_elapsed_time_exit_and_daily_nav_marks_open_position() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 90, 120, 95, {})
    account = AccountState(10000)
    engine = ExecutionEngine(ExecutionConfig(activation_latency_ms=0, base_slippage_bps=0, impact_bps_per_one_percent_depth=0))
    engine.submit_entry(account, event, PolicyDecision.MARKETABLE, 1.0)
    first = pd.Timestamp("2023-01-01T00:00:00Z")
    tape = simple_tape(pd.DatetimeIndex([first]), [100])
    engine.process_entry_row(account, first, tape.iloc[0])
    record = engine.record_utc_day_end(account, pd.Timestamp("2023-01-02T00:00:00Z"), 105)
    assert account.position is not None and record.unrealized_pnl > 0


def test_label_has_no_time_horizon_and_censors_unresolved() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 104, 99, {})
    index = pd.date_range("2023-01-01T00:00:01Z", periods=100, freq="1s")
    label = label_first_passage(event, simple_tape(index, [100.5] * 100), passive_entry=False, config=ExecutionConfig(activation_latency_ms=0))
    assert label.status == "UNRESOLVED_CENSORED" and label.event_end is None


from system.metrics import AccountMetrics, select_pre2024_configuration, summarize_account  # noqa: E402


def test_closed_trade_and_metrics_use_continuous_nav() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 102, 99, {})
    account = AccountState(10000)
    engine = ExecutionEngine(ExecutionConfig(activation_latency_ms=0, base_slippage_bps=0, impact_bps_per_one_percent_depth=0))
    engine.submit_entry(account, event, PolicyDecision.MARKETABLE, 1.0)
    index = pd.to_datetime(["2023-01-01T00:00:00Z", "2023-01-01T00:01:00Z"])
    tape = simple_tape(index, [100, 102.1])
    engine.process_entry_row(account, index[0], tape.iloc[0])
    engine.process_position_row(account, index[1], tape.iloc[1])
    metrics = summarize_account(account, pd.Timestamp("2023-01-01T00:00:00Z"), pd.Timestamp("2023-01-03T00:00:00Z"), 102.1)
    assert len(account.closed_trades) == 1 and metrics.completed_trades == 1 and metrics.calendar_days == 2 and metrics.end_nav > 10000


def test_configuration_selection_does_not_cap_growth_at_target() -> None:
    low = AccountMetrics(10000, 11000, 1.1, 0.1, 100, 0.00095, 0.1, 20, 0.6, 1.5, 0.01, 0.5, 0.05, False)
    high = AccountMetrics(10000, 40000, 4.0, 3.0, 100, 0.014, 0.3, 50, 0.55, 1.4, 0.02, 0.6, 1.5, False)
    selected, _ = select_pre2024_configuration([("low", low), ("high", high)])
    assert selected == "high"


from system.model import ChronologicalEventModel, ModelConfig  # noqa: E402


def test_chronological_event_model_fits_and_scores() -> None:
    rng = np.random.default_rng(11)
    count = 240
    x1 = rng.normal(size=count)
    x2 = rng.normal(size=count)
    target = (x1 + 0.4 * x2 > 0).astype(int)
    rows = pd.DataFrame(
        {
            "event_start": pd.date_range("2022-01-01", periods=count, freq="1h", tz="UTC"),
            "event_end": pd.date_range("2022-01-01T00:30:00Z", periods=count, freq="1h"),
            "target_before_stop": target,
            "net_r": np.where(target, 1.5 + 0.1 * x1, -1.0),
            "passive_filled": (x2 > -0.2).astype(int),
            "x1": x1,
            "x2": x2,
        }
    )
    model = ChronologicalEventModel(ModelConfig(min_samples_leaf=10, max_iter=80)).fit(rows)
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 104, 99, {"x1": 2.0, "x2": 0.5})
    scored = model.score(event, risk_fraction=0.02, winner_net_r=1.5, loser_net_r=-1.0, fixed_cost_fraction=0.0005)
    assert 0 <= scored.win_probability <= 1 and 0 <= scored.passive_fill_probability <= 1 and np.isfinite(scored.expected_log_growth)


from system.canonical_adapter import causal_asof_join, normalize_trade_bars  # noqa: E402


def test_canonical_adapter_joins_by_information_availability_not_source_time() -> None:
    trade = pd.DataFrame(
        {
            "start_time_ms": [0, 300000],
            "available_at_ms": [300000, 600000],
            "open": [100, 101],
            "high": [102, 103],
            "low": [99, 100],
            "close": [101, 102],
            "volume": [10, 11],
        }
    )
    base = normalize_trade_bars(trade)
    auxiliary = pd.DataFrame(
        {"available_at_ms": [299999, 600001], "mark_close": [100.5, 102.5]},
        index=pd.to_datetime(["1970-01-01T00:04:00Z", "1970-01-01T00:09:00Z"]),
    )
    joined = causal_asof_join(base, auxiliary)
    assert joined.iloc[0]["mark_close"] == 100.5 and joined.iloc[1]["mark_close"] == 100.5


from system.coarse import CoarseExecutionConfig, CoarseEventReplay, label_candidate_on_bars  # noqa: E402


def execution_bars(starts: list[str], opens: list[float], highs: list[float], lows: list[float], closes: list[float]) -> pd.DataFrame:
    start_index = pd.to_datetime(starts)
    availability = start_index + pd.Timedelta(minutes=1)
    return pd.DataFrame(
        {"bar_start": start_index, "open": opens, "high": highs, "low": lows, "close": closes, "mark_close": closes, "spread_bps": 1.0},
        index=availability,
    )


def test_coarse_label_uses_first_bar_strictly_after_500ms_and_stop_first() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:01:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 102, 99, {})
    coarse_bars = execution_bars(["2023-01-01T00:01:00Z", "2023-01-01T00:02:00Z"], [100, 100], [101, 103], [99, 97], [100, 101])
    label = label_candidate_on_bars(event, coarse_bars, passive=False, config=CoarseExecutionConfig(market_slippage_bps=0, stop_slippage_bps=0, minimum_spread_bps=0))
    assert label.entry_time == pd.Timestamp("2023-01-01T00:02:00Z") and label.status == "STOP" and label.target_before_stop == 0


def test_coarse_passive_touch_is_not_a_fill() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION, 1, 101, 100, 98, 105, 99, {})
    coarse_bars = execution_bars(["2023-01-01T00:01:00Z", "2023-01-01T00:02:00Z"], [101, 101], [102, 102], [100, 100.1], [101, 101])
    label = label_candidate_on_bars(event, coarse_bars, passive=True)
    assert label.passive_filled == 0 and label.status == "UNRESOLVED_NO_FILL"


from system.research_pipeline import InstrumentRule, ResearchConfiguration, encode_event_features, score_candidates_walk_forward  # noqa: E402


def test_event_replay_blocks_global_slot_until_barrier_is_available() -> None:
    coarse_bars = execution_bars(
        ["2023-01-01T00:01:00Z", "2023-01-01T00:02:00Z", "2023-01-01T00:03:00Z", "2023-01-01T00:04:00Z"],
        [100, 100, 100, 100],
        [100.5, 102.5, 100.5, 102.5],
        [99.5, 99.5, 99.5, 99.5],
        [100, 102, 100, 102],
    )
    first = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 102, 99, {})
    blocked = EventCandidate(pd.Timestamp("2023-01-01T00:02:30Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 102, 99, {})
    after = EventCandidate(pd.Timestamp("2023-01-01T00:03:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 102, 99, {})
    scored = [ScoredCandidate(candidate, 0.7, 0.5, 0.1, 0.01, 0.01) for candidate in (first, blocked, after)]
    account = CoarseEventReplay({"BTCUSDT": coarse_bars}, CoarseExecutionConfig(market_slippage_bps=0, stop_slippage_bps=0, minimum_spread_bps=0)).run(
        scored,
        GlobalSlotPolicy(0.55),
        RiskConfig(0.01, 5, 0.001),
        pd.Timestamp("2023-01-01T00:00:00Z"),
        pd.Timestamp("2023-01-02T00:00:00Z"),
    )
    assert len(account.closed_trades) == 2
    assert account.closed_trades[0].closed_at == pd.Timestamp("2023-01-01T00:03:00Z")
    assert account.closed_trades[1].opened_at == pd.Timestamp("2023-01-01T00:04:00Z")


def test_walk_forward_model_is_ready_at_interval_start_without_future_labels() -> None:
    rows = []
    for index in range(120):
        timestamp = pd.Timestamp("2022-01-01T00:00:00Z") + pd.Timedelta(hours=index)
        candidate = EventCandidate(timestamp, "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 104, 99, {"signal": float(index % 7)})
        row = {
            "event_start": timestamp,
            "event_end": timestamp + pd.Timedelta(minutes=30),
            "target_before_stop": int(index % 2 == 0),
            "net_r": 1.5 if index % 2 == 0 else -1.0,
            "passive_filled": int(index % 3 != 0),
        }
        row.update(encode_event_features(candidate))
        rows.append(row)
    labels = pd.DataFrame(rows)
    eval_start = pd.Timestamp("2023-01-01T00:00:00Z")
    candidates = [EventCandidate(eval_start + pd.Timedelta(minutes=minute), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 104, 99, {"signal": 5.0}) for minute in (0, 30, 60)]
    configuration = ResearchConfiguration(
        "test",
        ("BTCUSDT", "ETHUSDT"),
        ModelConfig(min_samples_leaf=5, max_iter=30, calibration_fraction=0.2),
        7,
        15,
        0.55,
        RiskConfig(0.01, 5, 0.001),
        (InstrumentRule("BTCUSDT", 0.001, 0.001), InstrumentRule("ETHUSDT", 0.01, 0.01)),
    )
    scored, ledger = score_candidates_walk_forward(candidates, labels, configuration, eval_start, eval_start + pd.Timedelta(days=1))
    assert len(scored) == 3 and ledger[0].model_activated_at == eval_start and ledger[0].latest_label_end < eval_start


from system.event_tape import EventTapeGlobalReplay  # noqa: E402


def test_event_tape_global_replay_uses_one_slot_and_500ms_activation() -> None:
    index = pd.to_datetime([
        "2023-01-01T00:00:00.400Z",
        "2023-01-01T00:00:00.500Z",
        "2023-01-01T00:00:01.500Z",
        "2023-01-01T00:00:02.500Z",
        "2023-01-01T00:00:03.500Z",
    ])
    tape = simple_tape(index, [100, 100, 102.1, 100, 102.1])
    first = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 102, 99, {})
    second = EventCandidate(pd.Timestamp("2023-01-01T00:00:02Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 102, 99, {})
    scored = [ScoredCandidate(first, 0.7, 1.0, 0.1, 0.01, 0.01), ScoredCandidate(second, 0.7, 1.0, 0.1, 0.01, 0.01)]
    replay = EventTapeGlobalReplay({"BTCUSDT": tape}, ExecutionConfig(activation_latency_ms=500, base_slippage_bps=0, impact_bps_per_one_percent_depth=0))
    account = replay.run(
        scored,
        GlobalSlotPolicy(0.55),
        RiskConfig(0.01, 5, 0.001),
        pd.Timestamp("2023-01-01T00:00:00Z"),
        pd.Timestamp("2023-01-02T00:00:00Z"),
    )
    assert len(account.closed_trades) == 2
    assert account.closed_trades[0].opened_at == pd.Timestamp("2023-01-01T00:00:00.500Z")
    assert account.closed_trades[1].opened_at == pd.Timestamp("2023-01-01T00:00:02.500Z")



def _manual_feature_frame(rows: list[dict[str, float]]) -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=len(rows), freq="5min", tz="UTC")
    defaults = {
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "volume": 100.0,
        "atr": 1.0,
        "last_swing_high": 101.0,
        "last_swing_low": 99.0,
        "previous_day_high": 105.0,
        "previous_day_low": 95.0,
        "previous_week_high": 110.0,
        "previous_week_low": 90.0,
        "bull_bos": 0.0,
        "bear_bos": 0.0,
        "bull_displacement": 0.0,
        "bear_displacement": 0.0,
        "bull_fvg_lower": np.nan,
        "bull_fvg_upper": np.nan,
        "bear_fvg_lower": np.nan,
        "bear_fvg_upper": np.nan,
        "close_location": 0.5,
        "body": 0.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows], index=index)


def test_liquidity_sweep_is_armed_then_requires_later_mss_displacement() -> None:
    frame = _manual_feature_frame(
        [
            {},
            {"high": 100.5, "low": 99.5, "close": 100.0},
            {"open": 100.0, "high": 100.5, "low": 98.0, "close": 100.0, "last_swing_low": 99.0},
            {
                "open": 100.2,
                "high": 102.5,
                "low": 100.0,
                "close": 102.0,
                "bull_displacement": 1.0,
                "bull_fvg_lower": 100.2,
                "bull_fvg_upper": 100.8,
                "close_location": 0.8,
                "body": 1.8,
            },
        ]
    )
    events_before_confirmation = generate_event_candidates(frame.iloc[:3], "BTCUSDT")
    events = generate_event_candidates(frame, "BTCUSDT")
    assert events_before_confirmation == []
    assert len(events) == 1
    assert events[0].timestamp == frame.index[3]
    assert events[0].family == EventFamily.LIQUIDITY_SWEEP_REVERSAL
    assert events[0].side == 1


def test_displacement_break_is_armed_then_requires_later_accepted_retest() -> None:
    frame = _manual_feature_frame(
        [
            {},
            {"last_swing_high": 100.0, "last_swing_low": 95.0},
            {
                "open": 99.5,
                "high": 103.0,
                "low": 99.5,
                "close": 102.5,
                "last_swing_high": 100.0,
                "last_swing_low": 95.0,
                "bull_bos": 1.0,
                "bull_displacement": 1.0,
                "bull_fvg_lower": 100.0,
                "bull_fvg_upper": 101.0,
                "close_location": 0.85,
                "body": 3.0,
            },
            {
                "open": 100.5,
                "high": 102.0,
                "low": 100.4,
                "close": 101.6,
                "last_swing_high": 100.0,
                "last_swing_low": 95.0,
                "close_location": 0.75,
                "body": 1.1,
            },
        ]
    )
    assert generate_event_candidates(frame.iloc[:3], "BTCUSDT") == []
    events = generate_event_candidates(frame, "BTCUSDT")
    assert len(events) == 1
    assert events[0].timestamp == frame.index[3]
    assert events[0].family == EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION


def test_policy_compares_action_specific_utility_not_fill_threshold() -> None:
    timestamp = pd.Timestamp("2023-01-01", tz="UTC")
    first = EventCandidate(timestamp, "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 104, 99, {})
    second = EventCandidate(timestamp, "ETHUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 104, 99, {})
    passive_edge = ScoredCandidate(
        first,
        0.6,
        0.4,
        0.20,
        0.012,
        0.010,
        passive_win_probability=0.8,
        market_expected_log_growth=0.002,
        passive_expected_log_growth=0.012,
        market_lower_confidence_score=0.001,
        passive_lower_confidence_score=0.010,
        preferred_action="PASSIVE_RETEST",
    )
    market_edge = ScoredCandidate(
        second,
        0.7,
        0.5,
        0.9,
        0.009,
        0.008,
        passive_win_probability=0.5,
        market_expected_log_growth=0.009,
        passive_expected_log_growth=-0.001,
        market_lower_confidence_score=0.008,
        passive_lower_confidence_score=-0.002,
        preferred_action="MARKETABLE",
    )
    selected = GlobalSlotPolicy(passive_fill_threshold=0.95).choose([passive_edge, market_edge], True)
    assert selected.scored == passive_edge
    assert selected.action == PolicyDecision.PASSIVE_RETEST


def test_passive_queue_uses_resting_side_and_correct_aggressor() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION, 1, 101, 100, 98, 105, 99, {})
    engine = ExecutionEngine(ExecutionConfig(activation_latency_ms=0, passive_queue_multiple=1.0))
    account = AccountState(10000)
    engine.submit_entry(account, event, PolicyDecision.PASSIVE_RETEST, 1.0)
    row = pd.Series({"bid": 99.9, "ask": 100.1, "last": 99.8, "mark": 99.9, "trade_volume": 3.0, "bid_size": 2.0, "ask_size": 1000.0, "aggressor_side": -1.0})
    engine.process_entry_row(account, pd.Timestamp("2023-01-01T00:00:01Z"), row)
    assert account.position is not None and account.position.quantity == 1.0

    blocked = AccountState(10000)
    engine.submit_entry(blocked, event, PolicyDecision.PASSIVE_RETEST, 1.0)
    wrong_side = row.copy()
    wrong_side["aggressor_side"] = 1.0
    engine.process_entry_row(blocked, pd.Timestamp("2023-01-01T00:00:01Z"), wrong_side)
    assert blocked.position is None


def test_partial_entry_remainder_is_cancelled_when_position_closes() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION, 1, 101, 100, 98, 105, 99, {})
    engine = ExecutionEngine(ExecutionConfig(activation_latency_ms=0, passive_queue_multiple=0.0, base_slippage_bps=0, impact_bps_per_one_percent_depth=0))
    account = AccountState(10000)
    engine.submit_entry(account, event, PolicyDecision.PASSIVE_RETEST, 2.0)
    fill_row = pd.Series({"bid": 99.9, "ask": 100.1, "last": 99.8, "mark": 100.0, "trade_volume": 1.0, "bid_size": 0.0, "ask_size": 10.0, "aggressor_side": -1.0})
    timestamp = pd.Timestamp("2023-01-01T00:00:01Z")
    engine.process_entry_row(account, timestamp, fill_row)
    assert account.position is not None and account.pending_entry is not None
    stop_row = fill_row.copy()
    stop_row["mark"] = 97.5
    stop_row["bid"] = 97.4
    stop_row["ask"] = 97.6
    stop_row["trade_volume"] = 0.0
    engine.process_position_row(account, timestamp + pd.Timedelta(seconds=1), stop_row)
    assert account.position is None and account.pending_entry is None


def test_actual_fill_is_capped_by_loss_budget() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 110, 99, {})
    engine = ExecutionEngine(ExecutionConfig(activation_latency_ms=0, base_slippage_bps=0, impact_bps_per_one_percent_depth=0))
    account = AccountState(10000)
    engine.submit_entry(account, event, PolicyDecision.MARKETABLE, 100.0, loss_budget=10.0, stop_fee_rate=0.0)
    row = pd.Series({"bid": 100.0, "ask": 100.0, "last": 100.0, "mark": 100.0, "trade_volume": 1000.0, "bid_size": 1000.0, "ask_size": 1000.0})
    engine.process_entry_row(account, pd.Timestamp("2023-01-01T00:00:00Z"), row)
    assert account.position is not None
    worst_case = account.position.quantity * (account.position.average_entry_price - event.stop_reference) + account.position.entry_fees
    assert worst_case <= 10.0 + 1e-9


def test_coarse_stop_uses_adverse_gap_open_not_trigger_price() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 110, 99, {})
    coarse_bars = execution_bars(
        ["2023-01-01T00:01:00Z", "2023-01-01T00:02:00Z"],
        [100.0, 90.0],
        [101.0, 92.0],
        [99.0, 89.0],
        [100.0, 91.0],
    )
    label = label_candidate_on_bars(event, coarse_bars, passive=False, config=CoarseExecutionConfig(market_slippage_bps=0, stop_slippage_bps=0, minimum_spread_bps=0))
    assert label.status == "STOP"
    assert label.net_r is not None and label.net_r < -4.0


def test_canonical_adapter_rejects_pre_source_availability() -> None:
    bad = pd.DataFrame(
        {
            "start_time_ms": [1000],
            "available_at_ms": [999],
            "open": [100],
            "high": [101],
            "low": [99],
            "close": [100],
            "volume": [1],
        }
    )
    try:
        normalize_trade_bars(bad)
    except RuntimeError as exc:
        assert "before its source timestamp" in str(exc)
    else:
        raise AssertionError("pre-source availability was accepted")


def test_event_tape_replay_exercises_structural_invalidation() -> None:
    index = pd.to_datetime(["2023-01-01T00:00:00.500Z", "2023-01-01T00:00:01.500Z"])
    tape = simple_tape(index, [100.0, 100.1])
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 110, 99, {})
    scored = [ScoredCandidate(event, 0.7, 1.0, 0.1, 0.01, 0.01)]
    replay = EventTapeGlobalReplay({"BTCUSDT": tape}, ExecutionConfig(activation_latency_ms=500, base_slippage_bps=0, impact_bps_per_one_percent_depth=0))
    account = replay.run(
        scored,
        GlobalSlotPolicy(0.55),
        RiskConfig(0.01, 5, 0.001),
        pd.Timestamp("2023-01-01T00:00:00Z"),
        pd.Timestamp("2023-01-02T00:00:00Z"),
        invalidation_timestamps={"BTCUSDT": {index[1]}},
    )
    assert len(account.closed_trades) == 1
    assert account.closed_trades[0].exit_reason == ExitReason.STRUCTURAL_INVALIDATION.value


def test_action_specific_model_does_not_copy_market_outcome_into_passive_nonfills() -> None:
    rng = np.random.default_rng(23)
    count = 300
    x = rng.normal(size=count)
    market_win = (x > -0.2).astype(int)
    passive_fill = (x > 0.8).astype(int)
    passive_win = (x > 1.2).astype(float)
    rows = pd.DataFrame(
        {
            "event_start": pd.date_range("2022-01-01", periods=count, freq="1h", tz="UTC"),
            "event_end": pd.date_range("2022-01-01T00:30:00Z", periods=count, freq="1h"),
            "target_before_stop": market_win,
            "net_r": np.where(market_win, 1.2, -1.0),
            "market_target_before_stop": market_win,
            "market_net_r": np.where(market_win, 1.2, -1.0),
            "passive_filled": passive_fill,
            "passive_target_before_stop": np.where(passive_fill, passive_win, np.nan),
            "passive_net_r": np.where(passive_fill, np.where(passive_win, 2.0, -1.0), 0.0),
            "x": x,
        }
    )
    model = ChronologicalEventModel(ModelConfig(min_samples_leaf=8, max_iter=60)).fit(rows)
    event = EventCandidate(
        pd.Timestamp("2023-01-01T00:00:00Z"),
        "BTCUSDT",
        EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        1,
        100,
        100,
        98,
        104,
        99,
        {"x": -1.0},
    )
    scored = model.score(
        event,
        risk_fraction=0.02,
        winner_net_r=1.2,
        loser_net_r=-1.0,
        fixed_cost_fraction=0.0,
        passive_winner_net_r=2.0,
        passive_loser_net_r=-1.0,
    )
    assert scored.market_expected_log_growth is not None
    assert scored.passive_expected_log_growth is not None
    assert scored.passive_expected_log_growth != scored.market_expected_log_growth
    assert abs(scored.passive_expected_log_growth) < abs(scored.market_expected_log_growth)


def test_candidate_generation_is_prefix_invariant() -> None:
    frame = _manual_feature_frame(
        [
            {},
            {},
            {"low": 98.0, "close": 100.0, "last_swing_low": 99.0},
            {
                "open": 100.0,
                "high": 102.5,
                "low": 100.0,
                "close": 102.0,
                "bull_displacement": 1.0,
                "bull_fvg_lower": 100.2,
                "bull_fvg_upper": 100.8,
                "close_location": 0.8,
                "body": 2.0,
            },
            {"high": 103.0, "low": 101.0, "close": 102.5},
        ]
    )
    short = generate_event_candidates(frame.iloc[:4], "BTCUSDT")
    long = [event for event in generate_event_candidates(frame, "BTCUSDT") if event.timestamp <= frame.index[3]]
    assert short == long


def test_coarse_execution_accepts_bar_start_exactly_at_activation_time() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:59.500Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 98, 110, 99, {})
    coarse_bars = execution_bars(
        ["2023-01-01T00:01:00Z", "2023-01-01T00:02:00Z"],
        [100.0, 100.0],
        [101.0, 101.0],
        [99.0, 99.0],
        [100.0, 100.0],
    )
    label = label_candidate_on_bars(event, coarse_bars, passive=False)
    assert label.entry_time == pd.Timestamp("2023-01-01T00:01:00Z")


def test_duplicate_event_timestamps_require_and_respect_sequence() -> None:
    from system.execution import validate_tape

    index = pd.to_datetime(["2023-01-01T00:00:00Z", "2023-01-01T00:00:00Z"])
    tape = simple_tape(index, [100.0, 100.1])
    try:
        validate_tape(tape.drop(columns=["aggressor_side"]))
    except ValueError as exc:
        assert "sequence" in str(exc)
    else:
        raise AssertionError("duplicate timestamps without sequence were accepted")
    tape["sequence"] = [1, 2]
    validated = validate_tape(tape)
    assert len(validated) == 2


def test_daily_nav_marks_realistic_closeout_value_including_exit_cost() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 90, 120, 95, {})
    account = AccountState(10000)
    engine = ExecutionEngine(ExecutionConfig(activation_latency_ms=0, base_slippage_bps=0, impact_bps_per_one_percent_depth=0))
    engine.submit_entry(account, event, PolicyDecision.MARKETABLE, 1.0)
    entry_row = pd.Series({"bid": 99.9, "ask": 100.0, "last": 100.0, "mark": 100.0, "trade_volume": 10.0, "bid_size": 100.0, "ask_size": 100.0})
    timestamp = pd.Timestamp("2023-01-01T00:00:00Z")
    engine.process_entry_row(account, timestamp, entry_row)
    closeout_row = entry_row.copy()
    closeout_row["bid"] = 99.0
    closeout_row["ask"] = 101.0
    mark_only, _ = engine.mark_nav(account, 100.0)
    record = engine.record_utc_day_end(account, pd.Timestamp("2023-01-02T00:00:00Z"), 100.0, closeout_row)
    assert record.nav < mark_only
    assert record.unrealized_pnl < 0


def test_final_metrics_can_use_executable_closeout_not_mark() -> None:
    event = EventCandidate(pd.Timestamp("2023-01-01T00:00:00Z"), "BTCUSDT", EventFamily.LIQUIDITY_SWEEP_REVERSAL, 1, 100, 100, 90, 120, 95, {})
    account = AccountState(10000)
    engine = ExecutionEngine(ExecutionConfig(activation_latency_ms=0, base_slippage_bps=0, impact_bps_per_one_percent_depth=0))
    engine.submit_entry(account, event, PolicyDecision.MARKETABLE, 1.0)
    row = pd.Series({"bid": 100.0, "ask": 100.0, "last": 100.0, "mark": 100.0, "trade_volume": 10.0, "bid_size": 100.0, "ask_size": 100.0})
    engine.process_entry_row(account, pd.Timestamp("2023-01-01T00:00:00Z"), row)
    marked = summarize_account(account, pd.Timestamp("2023-01-01T00:00:00Z"), pd.Timestamp("2023-01-02T00:00:00Z"), 100.0)
    liquidatable = summarize_account(
        account,
        pd.Timestamp("2023-01-01T00:00:00Z"),
        pd.Timestamp("2023-01-02T00:00:00Z"),
        100.0,
        final_closeout_price=99.0,
        final_closeout_fee_rate=0.00055,
    )
    assert liquidatable.end_nav < marked.end_nav
