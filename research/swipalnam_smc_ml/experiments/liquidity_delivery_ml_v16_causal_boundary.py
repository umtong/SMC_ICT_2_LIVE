#!/usr/bin/env python3
"""V16: causally active features and exact evaluation-boundary account state.

V15 supplies the dual-auction SMC/ICT ontology:
  external liquidity raid -> reclaim/MSS -> first mitigation, and
  decisive BOS/displacement -> first mitigation -> opposing liquidity.

This revision changes no trade thesis.  It makes model fitting and account
selection valid at every cutoff:
- only features with real variation in the data available at that cutoff are
  fitted;
- pending orders whose future fill is beyond the evaluation boundary remain
  pending at that boundary;
- positions still open at the boundary are marked to executable liquidation
  value, without using their later strategy exit as selection information;
- boundary marks affect NAV but are not counted as completed trades.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import liquidity_delivery_ml_v15_dual_auction as v15  # noqa: E402

v1 = v15.v1
v3 = v15.v3
v5 = v15.v5

_BASE_RAW = v1.raw_candidates


def _active_columns(frame: pd.DataFrame) -> list[str]:
    """Columns with at least two causally observed finite values."""
    active: list[str] = []
    for name in frame.columns:
        values = frame[name].replace([np.inf, -np.inf], np.nan).dropna()
        if values.nunique() >= 2:
            active.append(name)
    return active


def prequential_scores_v16(
    frame: pd.DataFrame,
    eligible: pd.Series,
    start_ms: int,
    end_ms: int,
    policy: str,
    min_train: int = 50,
) -> pd.Series:
    """Causal fill-adjusted expectancy with per-cutoff feature availability."""
    scores = pd.Series(np.nan, index=frame.index, dtype=float)
    x = v15.causal_feature_matrix(frame)
    if policy == "frozen":
        cutoffs = [start_ms]
        windows = [(start_ms, end_ms)]
    else:
        frequency = "MS" if policy == "monthly" else "QS"
        dates = list(
            pd.date_range(
                pd.Timestamp(start_ms, unit="ms", tz="UTC"),
                pd.Timestamp(end_ms, unit="ms", tz="UTC"),
                freq=frequency,
                inclusive="left",
            )
        )
        cutoffs = [start_ms] + [
            int(timestamp.value // 1_000_000)
            for timestamp in dates
            if int(timestamp.value // 1_000_000) > start_ms
        ]
        windows = [
            (cutoff, cutoffs[index + 1] if index + 1 < len(cutoffs) else end_ms)
            for index, cutoff in enumerate(cutoffs)
        ]

    for cutoff, (window_start, window_end) in zip(cutoffs, windows):
        resolved = (
            eligible
            & frame["resolved"].fillna(False)
            & (frame["label_end_time_ms"] < cutoff)
        )
        outcome_train = (
            resolved
            & frame["filled"].fillna(False)
            & frame["net_r"].notna()
        )
        predict = (
            eligible
            & (frame["decision_time_ms"] >= window_start)
            & (frame["decision_time_ms"] < window_end)
        )
        if (
            int(resolved.sum()) < min_train
            or int(outcome_train.sum()) < min_train
            or not predict.any()
        ):
            continue

        outcome_y = frame.loc[outcome_train, "net_r"].astype(float).clip(-8, 12)
        binary_y = (outcome_y > 0).astype(int)
        if binary_y.nunique() < 2:
            continue

        outcome_columns = _active_columns(x.loc[outcome_train])
        if not outcome_columns:
            continue
        outcome_x = x[outcome_columns]
        seed = 7 + int(cutoff // v1.DAY_MS) % 997
        outcome_classifier, outcome_regressor = v15.causal_model_pair(seed)
        outcome_classifier.fit(outcome_x.loc[outcome_train], binary_y)
        outcome_regressor.fit(outcome_x.loc[outcome_train], outcome_y)
        win_probability = outcome_classifier.predict_proba(
            outcome_x.loc[predict]
        )[:, 1]
        conditional_r = outcome_regressor.predict(outcome_x.loc[predict])

        fill_y = frame.loc[resolved, "filled"].astype(int)
        if fill_y.nunique() >= 2:
            fill_columns = _active_columns(x.loc[resolved])
            if fill_columns:
                fill_classifier = HistGradientBoostingClassifier(
                    learning_rate=0.05,
                    max_iter=140,
                    max_leaf_nodes=15,
                    min_samples_leaf=20,
                    l2_regularization=0.8,
                    random_state=seed + 2,
                )
                fill_classifier.fit(x.loc[resolved, fill_columns], fill_y)
                fill_probability = fill_classifier.predict_proba(
                    x.loc[predict, fill_columns]
                )[:, 1]
            else:
                fill_probability = np.full(int(predict.sum()), float(fill_y.mean()))
        else:
            fill_probability = np.full(int(predict.sum()), float(fill_y.mean()))

        conditional_quality = (
            conditional_r * (0.55 + win_probability)
            + 0.2 * (win_probability - 0.5)
        )
        scores.loc[predict] = (
            fill_probability * conditional_quality
            - (1.0 - fill_probability) * 0.05
        )
    return scores


def raw_candidates_v16(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    candidates = _BASE_RAW(symbol, frame)
    if not candidates.empty and "target_reference_code" in candidates:
        candidates = candidates.copy()
        # V9 used Python's salted hash of a name as a model feature.  The target
        # distance and ladder rank carry the economics; neutralize the opaque ID.
        candidates["target_reference_code"] = 0.0
    return candidates


def _finite_int(value: Any) -> int | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return int(numeric)


def _boundary_safe_frame(
    frame: pd.DataFrame,
    minute_by_symbol: Mapping[str, pd.DataFrame],
    end_ms: int,
    slippage_bps: float,
) -> pd.DataFrame:
    """Hide all order and position outcomes strictly after ``end_ms``."""
    safe = frame.copy(deep=True)
    slippage = float(slippage_bps) / 10_000
    for index, row in safe.iterrows():
        decision = _finite_int(row.get("decision_time_ms"))
        if decision is None or decision >= end_ms:
            continue

        order_end = _finite_int(row.get("order_end_time_ms"))
        if order_end is not None and order_end > end_ms:
            safe.at[index, "order_end_time_ms"] = end_ms

        if not bool(row.get("filled", False)):
            if order_end is None or order_end >= end_ms:
                safe.at[index, "resolved"] = False
                safe.at[index, "label_end_time_ms"] = end_ms
            continue

        entry_time = _finite_int(row.get("entry_time_ms"))
        if entry_time is None or entry_time >= end_ms:
            safe.at[index, "filled"] = False
            safe.at[index, "resolved"] = False
            safe.at[index, "entry_time_ms"] = np.nan
            safe.at[index, "entry_price"] = np.nan
            safe.at[index, "exit_time_ms"] = np.nan
            safe.at[index, "exit_price"] = np.nan
            safe.at[index, "gross_pnl_per_unit"] = 0.0
            safe.at[index, "net_r"] = np.nan
            safe.at[index, "label_end_time_ms"] = end_ms
            safe.at[index, "order_end_time_ms"] = end_ms
            safe.at[index, "exit_reason"] = "pending_at_evaluation_end"
            continue

        exit_time = _finite_int(row.get("exit_time_ms"))
        if exit_time is not None and exit_time < end_ms:
            continue

        symbol = str(row["symbol"])
        minute = minute_by_symbol[symbol]
        direction = int(row["direction"])
        entry = float(row["entry_price"])
        stop = float(row["stop_price"])
        target = float(row["target_price"])
        mark = v5._mark_close(minute, end_ms)
        executable_mark = mark * (1 - direction * slippage)

        proxy = row.copy()
        proxy["exit_time_ms"] = end_ms
        proxy["exit_reason"] = "open_at_evaluation_end_mark"
        partial_time, tp1 = v5._partial_event(proxy, minute)
        if partial_time is not None and int(partial_time) >= end_ms:
            partial_time = None
        partial_fraction = 0.40 if partial_time is not None else 0.0
        remaining_fraction = 1.0 - partial_fraction
        gross_per_unit = (
            partial_fraction * (tp1 - entry) * direction
            + remaining_fraction * (executable_mark - entry) * direction
        )
        risk = (entry - stop) * direction

        safe.at[index, "exit_time_ms"] = end_ms
        safe.at[index, "exit_price"] = executable_mark
        safe.at[index, "exit_reason"] = "open_at_evaluation_end_mark"
        safe.at[index, "gross_pnl_per_unit"] = gross_per_unit
        safe.at[index, "net_r"] = (
            gross_per_unit / risk if risk > 0 else np.nan
        )
        safe.at[index, "resolved"] = False
        safe.at[index, "label_end_time_ms"] = end_ms
    return safe


def _recalculate_completed_trade_statistics(metrics: dict[str, Any]) -> None:
    trades = metrics.get("trades") or []
    completed = [
        trade
        for trade in trades
        if str(trade.get("exit_reason")) != "open_at_evaluation_end_mark"
    ]
    open_marks = len(trades) - len(completed)
    pnl = np.array([float(trade["net_pnl"]) for trade in completed], dtype=float)
    positive = float(pnl[pnl > 0].sum()) if len(pnl) else 0.0
    negative = float(-pnl[pnl < 0].sum()) if len(pnl) else 0.0
    positive_only = np.maximum(pnl, 0)
    metrics["completed_trades"] = len(completed)
    metrics["open_positions_at_end"] = open_marks
    metrics["win_rate"] = float(np.mean(pnl > 0)) if len(pnl) else None
    metrics["profit_factor"] = positive / negative if negative > 0 else None
    metrics["top_5_pnl_share"] = (
        float(np.sort(positive_only)[-5:].sum() / positive_only.sum())
        if len(positive_only) and positive_only.sum() > 0
        else None
    )
    metrics["evaluation_boundary_policy"] = (
        "future fills hidden; open positions valued at executable boundary mark; "
        "boundary marks excluded from completed-trade statistics"
    )


def account_sim_v16(
    frame: pd.DataFrame,
    minute_by_symbol: Mapping[str, pd.DataFrame],
    account: Any,
    start_ms: int,
    end_ms: int,
    threshold: float,
    initial_nav: float = 10_000.0,
) -> dict[str, Any]:
    safe = _boundary_safe_frame(
        frame,
        minute_by_symbol,
        end_ms,
        float(account.slippage_bps),
    )
    replacement_sigma = float(getattr(account, "replacement_sigma", 0.0))
    chosen = v15.chosen_candidates_causal(safe, threshold, replacement_sigma)
    original_count = int(
        (safe["ml_score"].notna() & (safe["ml_score"] >= threshold)).sum()
    )
    metrics = v15.account_sim_exact_causal(
        chosen,
        minute_by_symbol,
        account,
        start_ms,
        end_ms,
        threshold,
        initial_nav,
    )
    metrics["pending_order_replacements_or_competition_drops"] = max(
        0, original_count - len(chosen)
    )
    metrics["replacement_sigma"] = replacement_sigma
    _recalculate_completed_trade_statistics(metrics)
    return metrics


v1.prequential_scores = prequential_scores_v16
v1.raw_candidates = raw_candidates_v16
v1.account_sim = account_sim_v16


def self_test_v16() -> None:
    v1.self_test()
    sample = pd.DataFrame(
        {
            "symbol": ["BTCUSDT"] * 120,
            "direction": np.where(np.arange(120) % 2 == 0, 1, -1),
            "displacement_body_atr": np.linspace(0.2, 2.0, 120),
        }
    )
    x = v15.causal_feature_matrix(sample)
    active = _active_columns(x)
    assert active
    classifier, regressor = v15.causal_model_pair(41)
    classifier.fit(x[active], pd.Series(np.arange(120) % 2))
    regressor.fit(x[active], pd.Series(np.sin(np.arange(120) / 8)))
    assert np.isfinite(classifier.predict_proba(x[active].iloc[:3])).all()
    assert np.isfinite(regressor.predict(x[active].iloc[:3])).all()

    start = v1.utc_ms("2023-12-31T23:55:00Z")
    minute = pd.DataFrame(
        {
            "start_time_ms": start + np.arange(10) * v1.MINUTE_MS,
            "available_at_ms": start + (np.arange(10) + 1) * v1.MINUTE_MS,
            "open": np.linspace(100, 109, 10),
            "high": np.linspace(101, 110, 10),
            "low": np.linspace(99, 108, 10),
            "close": np.linspace(100.5, 109.5, 10),
            "turnover": 1_000_000.0,
        }
    )
    boundary = v1.utc_ms("2024-01-01T00:00:00Z")
    frame = pd.DataFrame(
        [
            {
                "candidate_id": "open-boundary",
                "symbol": "BTCUSDT",
                "direction": 1,
                "decision_time_ms": start,
                "order_end_time_ms": boundary + v1.DAY_MS,
                "filled": True,
                "resolved": True,
                "entry_time_ms": start + v1.MINUTE_MS,
                "entry_price": 101.0,
                "stop_price": 98.0,
                "target_price": 120.0,
                "exit_time_ms": boundary + v1.DAY_MS,
                "exit_price": 120.0,
                "exit_reason": "opposing_liquidity",
                "gross_pnl_per_unit": 19.0,
                "net_r": 6.0,
                "label_end_time_ms": boundary + v1.DAY_MS,
            }
        ]
    )
    safe = _boundary_safe_frame(frame, {"BTCUSDT": minute}, boundary, 1.0)
    assert int(safe.iloc[0]["exit_time_ms"]) == boundary
    assert safe.iloc[0]["exit_reason"] == "open_at_evaluation_end_mark"
    assert not bool(safe.iloc[0]["resolved"])
    assert float(safe.iloc[0]["exit_price"]) < 120.0
    print("V16_CAUSAL_BOUNDARY_SELF_TEST_PASS")


def main() -> int:
    if "--self-test" in sys.argv:
        self_test_v16()
        return 0
    return v3.main_v3()


if __name__ == "__main__":
    raise SystemExit(main())
