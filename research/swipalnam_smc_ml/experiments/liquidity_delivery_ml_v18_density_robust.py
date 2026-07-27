#!/usr/bin/env python3
"""V18: density-aware, concentration-resistant, rolling-regime SMC/ICT.

The price-action ontology remains unchanged:
1. confirmed external-liquidity raid -> reclaim/MSS -> first FVG/OB mitigation;
2. decisive BOS/displacement -> first FVG/OB mitigation -> next known liquidity.

V18 improves only the selection and deployment economics around those setups:
- stable structural context features instead of opaque category hashes;
- rolling causal model windows so stale regimes do not dominate indefinitely;
- fill- and slot-occupancy-adjusted execution expectancy;
- smoother confidence sizing so a few high-score trades do not dominate NAV;
- pre-2024 selection that explicitly rewards trade density, monthly breadth and
  growth that remains after removing the largest winners.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import liquidity_delivery_ml_v17_sparse_sweep as v17  # noqa: E402

v16 = v17.v16
v15 = v17.v15
v3 = v17.v3
v1 = v17.v1

_BASE_RAW = v1.raw_candidates

STRUCTURAL_FEATURES = [
    "liquidity_tier",
    "liquidity_is_external",
    "liquidity_is_session",
    "liquidity_is_daily_weekly",
    "zone_width_atr",
    "stop_distance_atr",
    "draw_distance_atr",
    "minutes_from_nearest_session_open",
    "opening_phase",
]
for feature in STRUCTURAL_FEATURES:
    if feature not in v1.FEATURES:
        v1.FEATURES.append(feature)


def _liquidity_context(name: str) -> tuple[float, float, float, float]:
    key = str(name).lower()
    if "confirmed_internal_bos" in key:
        return 0.0, 0.0, 0.0, 0.0
    if "week" in key or "day" in key:
        return 3.0, 1.0, 0.0, 1.0
    if "session" in key or "opening" in key or "4h" in key:
        return 2.0, 1.0, 1.0, 0.0
    if "swing" in key or "equal" in key:
        return 1.0, 1.0, 0.0, 0.0
    return 1.0, 1.0, 0.0, 0.0


def raw_candidates_v18(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    candidates = _BASE_RAW(symbol, frame)
    if candidates.empty:
        return candidates
    out = candidates.copy()
    tiers = out["swept_level_name"].astype(str).map(_liquidity_context)
    out["liquidity_tier"] = [item[0] for item in tiers]
    out["liquidity_is_external"] = [item[1] for item in tiers]
    out["liquidity_is_session"] = [item[2] for item in tiers]
    out["liquidity_is_daily_weekly"] = [item[3] for item in tiers]

    atr = pd.to_numeric(out["atr"], errors="coerce").replace(0, np.nan)
    reference = (
        pd.to_numeric(out["zone_low"], errors="coerce")
        + pd.to_numeric(out["zone_high"], errors="coerce")
    ) / 2
    out["zone_width_atr"] = (
        pd.to_numeric(out["zone_high"], errors="coerce")
        - pd.to_numeric(out["zone_low"], errors="coerce")
    ) / atr
    out["stop_distance_atr"] = (
        reference - pd.to_numeric(out["stop_anchor"], errors="coerce")
    ).abs() / atr
    out["draw_distance_atr"] = (
        pd.to_numeric(out["target_price"], errors="coerce") - reference
    ).abs() / atr

    dt = pd.to_datetime(out["decision_time_ms"], unit="ms", utc=True)
    minute_of_day = dt.dt.hour * 60 + dt.dt.minute
    session_opens = np.array([0, 7 * 60, 13 * 60, 21 * 60, 24 * 60], dtype=float)
    minute_values = minute_of_day.to_numpy(float)
    distance = np.min(
        np.abs(minute_values[:, None] - session_opens[None, :]), axis=1
    )
    out["minutes_from_nearest_session_open"] = np.minimum(distance, 180.0) / 180.0
    out["opening_phase"] = (distance <= 90.0).astype(float)
    return out


v1.raw_candidates = raw_candidates_v18


def _active_columns(frame: pd.DataFrame) -> list[str]:
    active: list[str] = []
    for name in frame.columns:
        values = frame[name].replace([np.inf, -np.inf], np.nan).dropna()
        if values.nunique() >= 2:
            active.append(name)
    return active


def _lookback_ms(policy: str) -> int | None:
    if policy == "monthly":
        return 210 * v1.DAY_MS
    if policy == "quarterly":
        return 420 * v1.DAY_MS
    return None


def _model_windows(start_ms: int, end_ms: int, policy: str) -> list[tuple[int, int]]:
    if policy == "frozen":
        return [(start_ms, end_ms)]
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
    return [
        (cutoff, cutoffs[index + 1] if index + 1 < len(cutoffs) else end_ms)
        for index, cutoff in enumerate(cutoffs)
    ]


def _robust_score_scale(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if not len(finite):
        return 0.10
    q25, q75 = np.quantile(finite, [0.25, 0.75])
    median_abs = float(np.median(np.abs(finite)))
    return max(float(q75 - q25), median_abs, 0.05)


def prequential_scores_v18(
    frame: pd.DataFrame,
    eligible: pd.Series,
    start_ms: int,
    end_ms: int,
    policy: str,
    min_train: int = 50,
) -> pd.Series:
    """Rolling causal execution value per expected global-slot occupancy."""
    scores = pd.Series(np.nan, index=frame.index, dtype=float)
    x = v15.causal_feature_matrix(frame)
    for cutoff, window_end in _model_windows(start_ms, end_ms, policy):
        window_start = cutoff
        lookback = _lookback_ms(policy)
        lower_bound = -np.inf if lookback is None else cutoff - lookback
        resolved = (
            eligible
            & frame["resolved"].fillna(False)
            & (frame["label_end_time_ms"] < cutoff)
            & (frame["decision_time_ms"] >= lower_bound)
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
        resolved_columns = _active_columns(x.loc[resolved])
        if not outcome_columns or not resolved_columns:
            continue

        seed = 17 + int(cutoff // v1.DAY_MS) % 997
        outcome_classifier, outcome_regressor = v15.causal_model_pair(seed)
        outcome_classifier.fit(x.loc[outcome_train, outcome_columns], binary_y)
        outcome_regressor.fit(x.loc[outcome_train, outcome_columns], outcome_y)

        fill_y = frame.loc[resolved, "filled"].astype(int)
        if fill_y.nunique() >= 2:
            fill_classifier = HistGradientBoostingClassifier(
                learning_rate=0.045,
                max_iter=150,
                max_leaf_nodes=15,
                min_samples_leaf=20,
                l2_regularization=1.0,
                random_state=seed + 2,
            )
            fill_classifier.fit(x.loc[resolved, resolved_columns], fill_y)
            fill_probability = fill_classifier.predict_proba(
                x.loc[predict, resolved_columns]
            )[:, 1]
            fill_reference = fill_classifier.predict_proba(
                x.loc[resolved, resolved_columns]
            )[:, 1]
        else:
            fill_probability = np.full(int(predict.sum()), float(fill_y.mean()))
            fill_reference = np.full(int(resolved.sum()), float(fill_y.mean()))

        occupancy_end = np.where(
            frame.loc[resolved, "filled"].fillna(False).to_numpy(bool),
            pd.to_numeric(frame.loc[resolved, "exit_time_ms"], errors="coerce"),
            pd.to_numeric(frame.loc[resolved, "order_end_time_ms"], errors="coerce"),
        )
        occupancy_minutes = np.clip(
            (occupancy_end - frame.loc[resolved, "decision_time_ms"].to_numpy(float))
            / v1.MINUTE_MS,
            1.0,
            3.0 * 24.0 * 60.0,
        )
        duration_regressor = HistGradientBoostingRegressor(
            loss="absolute_error",
            learning_rate=0.045,
            max_iter=140,
            max_leaf_nodes=15,
            min_samples_leaf=20,
            l2_regularization=1.0,
            random_state=seed + 3,
        )
        duration_regressor.fit(
            x.loc[resolved, resolved_columns], np.log1p(occupancy_minutes)
        )
        predicted_minutes = np.expm1(
            duration_regressor.predict(x.loc[predict, resolved_columns])
        )
        reference_minutes = np.expm1(
            duration_regressor.predict(x.loc[resolved, resolved_columns])
        )
        predicted_hours = np.clip(predicted_minutes / 60.0, 1 / 60, 72.0)
        reference_hours = np.clip(reference_minutes / 60.0, 1 / 60, 72.0)

        win_probability = outcome_classifier.predict_proba(
            x.loc[predict, outcome_columns]
        )[:, 1]
        conditional_r = outcome_regressor.predict(x.loc[predict, outcome_columns])
        reference_win = outcome_classifier.predict_proba(
            x.loc[resolved, outcome_columns]
        )[:, 1]
        reference_r = outcome_regressor.predict(x.loc[resolved, outcome_columns])

        conditional_quality = (
            conditional_r * (0.55 + win_probability)
            + 0.20 * (win_probability - 0.5)
        )
        reference_quality = (
            reference_r * (0.55 + reference_win)
            + 0.20 * (reference_win - 0.5)
        )
        raw = (
            fill_probability * conditional_quality
            / np.sqrt(1.0 + predicted_hours / 4.0)
            - (1.0 - fill_probability) * 0.025 * np.sqrt(1.0 + predicted_hours)
        )
        raw_reference = (
            fill_reference * reference_quality
            / np.sqrt(1.0 + reference_hours / 4.0)
            - (1.0 - fill_reference) * 0.025 * np.sqrt(1.0 + reference_hours)
        )
        scale = _robust_score_scale(np.asarray(raw_reference, dtype=float))
        calibrated = 0.5 + 0.5 * np.tanh(np.asarray(raw, dtype=float) / scale)
        scores.loc[predict] = calibrated
    return scores


v1.prequential_scores = prequential_scores_v18


def diversified_risk_multiplier(
    score: float, frame: Any, threshold: float, maximum: float
) -> float:
    denominator = max(1.0 - float(threshold), 0.15)
    normalized = float(np.clip((score - float(threshold)) / denominator, 0.0, 1.0))
    cap = min(float(maximum), 2.0)
    return 0.60 + (cap - 0.60) * normalized**0.75


v15.causal_risk_multiplier = diversified_risk_multiplier
v15.v7._risk_multiplier = diversified_risk_multiplier
v15.v5._risk_multiplier = diversified_risk_multiplier


def _growth_from_trade_returns(returns: np.ndarray, days: int) -> float:
    valid = returns[np.isfinite(returns) & (returns > -1)]
    if days <= 0 or not len(valid):
        return 0.0
    return float(np.exp(np.log1p(valid).sum() / days) - 1.0)


def _month_breadth(daily_nav: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    if not daily_nav:
        return 0.0, 0.0, 0.0, 0.0
    frame = pd.DataFrame(daily_nav)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame = frame.sort_values("time")
    frame["month"] = frame["time"].dt.to_period("M").astype(str)
    monthly = frame.groupby("month", sort=True)["nav"].agg(["first", "last"])
    returns = monthly["last"] / monthly["first"] - 1.0
    positive_share = float((returns > 0).mean()) if len(returns) else 0.0
    minimum = float(returns.min()) if len(returns) else 0.0
    standard_deviation = float(returns.std(ddof=0)) if len(returns) else 0.0
    active_share = float((returns != 0).mean()) if len(returns) else 0.0
    return positive_share, minimum, standard_deviation, active_share


def add_robust_metrics(
    metrics: dict[str, Any],
    frame: pd.DataFrame,
    start_ms: int,
    end_ms: int,
) -> dict[str, Any]:
    trades = [
        trade
        for trade in (metrics.get("trades") or [])
        if str(trade.get("exit_reason")) != "open_at_evaluation_end_mark"
    ]
    days = max(1, int(math.ceil((end_ms - start_ms) / v1.DAY_MS)))
    if not trades:
        metrics.update(
            {
                "top_1_pnl_share": None,
                "top_10_pnl_share": None,
                "profit_hhi": None,
                "effective_positive_trade_count": 0.0,
                "top1_removed_geometric_daily_growth": 0.0,
                "top5_removed_geometric_daily_growth": 0.0,
                "trades_per_day": 0.0,
                "monthly_positive_share": 0.0,
                "monthly_min_return": 0.0,
                "monthly_return_std": 0.0,
                "active_month_share": 0.0,
                "max_family_trade_share": None,
                "max_symbol_trade_share": None,
            }
        )
        return metrics

    pnl = np.array([float(trade["net_pnl"]) for trade in trades], dtype=float)
    returns = np.array(
        [
            float(trade["nav_after"]) / max(float(trade["nav_before"]), v1.EPS) - 1.0
            for trade in trades
        ],
        dtype=float,
    )
    positive = np.maximum(pnl, 0.0)
    positive_sum = float(positive.sum())
    order = np.argsort(positive)[::-1]
    metrics["top_1_pnl_share"] = (
        float(positive[order[:1]].sum() / positive_sum) if positive_sum > 0 else None
    )
    metrics["top_10_pnl_share"] = (
        float(positive[order[:10]].sum() / positive_sum) if positive_sum > 0 else None
    )
    metrics["profit_hhi"] = (
        float(np.square(positive / positive_sum).sum()) if positive_sum > 0 else None
    )
    metrics["effective_positive_trade_count"] = (
        float(1.0 / metrics["profit_hhi"])
        if metrics.get("profit_hhi") and metrics["profit_hhi"] > 0
        else 0.0
    )
    keep_top1 = np.ones(len(returns), dtype=bool)
    keep_top5 = np.ones(len(returns), dtype=bool)
    keep_top1[order[:1]] = False
    keep_top5[order[:5]] = False
    metrics["top1_removed_geometric_daily_growth"] = _growth_from_trade_returns(
        returns[keep_top1], days
    )
    metrics["top5_removed_geometric_daily_growth"] = _growth_from_trade_returns(
        returns[keep_top5], days
    )
    metrics["trades_per_day"] = len(trades) / days

    positive_share, minimum, std, active_share = _month_breadth(
        metrics.get("daily_nav") or []
    )
    metrics["monthly_positive_share"] = positive_share
    metrics["monthly_min_return"] = minimum
    metrics["monthly_return_std"] = std
    metrics["active_month_share"] = active_share

    lookup = frame.drop_duplicates("candidate_id").set_index("candidate_id")
    families: list[str] = []
    symbols: list[str] = []
    for trade in trades:
        candidate_id = str(trade["candidate_id"])
        symbols.append(str(trade["symbol"]))
        if candidate_id in lookup.index:
            row = lookup.loc[candidate_id]
            family = float(row.get("model_family", np.nan))
            families.append(str(int(family)) if np.isfinite(family) else "unknown")
        else:
            families.append("unknown")
    family_counts = pd.Series(families).value_counts(normalize=True)
    symbol_counts = pd.Series(symbols).value_counts(normalize=True)
    metrics["max_family_trade_share"] = (
        float(family_counts.max()) if len(family_counts) else None
    )
    metrics["max_symbol_trade_share"] = (
        float(symbol_counts.max()) if len(symbol_counts) else None
    )
    return metrics


_BASE_ACCOUNT_SIM = v16.account_sim_v16


def account_sim_v18(
    frame: pd.DataFrame,
    minute_by_symbol: Mapping[str, pd.DataFrame],
    account: Any,
    start_ms: int,
    end_ms: int,
    threshold: float,
    initial_nav: float = 10_000.0,
) -> dict[str, Any]:
    metrics = _BASE_ACCOUNT_SIM(
        frame,
        minute_by_symbol,
        account,
        start_ms,
        end_ms,
        threshold,
        initial_nav,
    )
    return add_robust_metrics(metrics, frame, start_ms, end_ms)


v1.account_sim = account_sim_v18


def setup_grid_v18() -> list[Any]:
    configs: list[Any] = []
    for timeframe in (1, 3, 5, 15):
        for sweep in (0.02, 0.06, 0.12):
            for body in (0.35, 0.55, 0.85):
                for fvg in (0.00, 0.02, 0.05):
                    overlaps = (False,) if fvg == 0 else (False, True)
                    for retrace in (0.50, 0.62, 0.705, 0.79):
                        for require_pd in (False, True):
                            for overlap in overlaps:
                                configs.append(
                                    v1.SetupConfig(
                                        timeframe,
                                        sweep,
                                        body,
                                        fvg,
                                        retrace,
                                        require_pd,
                                        overlap,
                                    )
                                )
    return configs


def account_grid_v18() -> list[Any]:
    return [
        v1.AccountConfig(
            risk_fraction=risk,
            leverage=leverage,
            replacement_sigma=replacement,
            confidence_risk_max=maximum,
        )
        for risk in (0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.18, 0.25, 0.30)
        for leverage in (5, 10, 20, 30, 50, 75, 100)
        for replacement in (0.0, 0.10, 0.25, 0.50)
        for maximum in (1.0, 1.4, 2.0)
    ]


def compact(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metrics.items()
        if key not in {"daily_nav", "trades"}
    }


def robust_objective(metrics: Mapping[str, Any]) -> float:
    growth_value = metrics.get("geometric_daily_growth")
    growth = float(growth_value) if growth_value is not None else -1.0
    no_top1 = float(metrics.get("top1_removed_geometric_daily_growth") or 0.0)
    no_top5 = float(metrics.get("top5_removed_geometric_daily_growth") or 0.0)
    drawdown = float(metrics.get("max_drawdown") or 0.0)
    trades = int(metrics.get("completed_trades") or 0)
    density = float(metrics.get("trades_per_day") or 0.0)
    monthly_positive = float(metrics.get("monthly_positive_share") or 0.0)
    active_months = float(metrics.get("active_month_share") or 0.0)
    top5 = float(metrics.get("top_5_pnl_share") or 1.0)
    top1 = float(metrics.get("top_1_pnl_share") or 1.0)
    family_share = float(metrics.get("max_family_trade_share") or 1.0)
    hhi = float(metrics.get("profit_hhi") or 1.0)
    effective = float(metrics.get("effective_positive_trade_count") or 0.0)
    return (
        5_500.0 * growth
        + 1_500.0 * no_top1
        + 3_000.0 * no_top5
        + 1.25 * math.log1p(trades)
        + 1.00 * min(density, 2.0)
        + 1.50 * monthly_positive
        + 0.50 * active_months
        + 0.20 * math.log1p(effective)
        + 1.50 * drawdown
        - 4.0 * max(0.0, top5 - 0.40)
        - 2.0 * max(0.0, top1 - 0.18)
        - 1.5 * max(0.0, family_share - 0.80)
        - 1.0 * hhi
    )


def structural_score(sample: pd.DataFrame, train_start: int, train_end: int) -> tuple[float, list[float], float]:
    quarters = np.linspace(train_start, train_end, 5, dtype=np.int64)
    means: list[float] = []
    for left, right in zip(quarters[:-1], quarters[1:]):
        segment = sample[
            (sample["decision_time_ms"] >= left)
            & (sample["decision_time_ms"] < right)
        ]["net_r"]
        means.append(float(segment.mean()) if len(segment) else -10.0)
    values = sample["net_r"].astype(float).to_numpy()
    positive_indices = np.flatnonzero(values > 0)
    positive_order = positive_indices[np.argsort(values[positive_indices])[::-1]] if len(positive_indices) else np.empty(0, dtype=int)
    keep = np.ones(len(values), dtype=bool)
    keep[positive_order[: min(5, len(positive_order))]] = False
    trimmed = float(np.mean(values[keep])) if keep.any() else float(np.mean(values))
    q25 = float(np.quantile(values, 0.25))
    score = (
        0.25 * float(np.mean(values))
        + 0.20 * float(np.median(values))
        + 0.20 * q25
        + 0.15 * min(means)
        + 0.15 * trimmed
        + 0.05 * math.log1p(len(values))
    )
    return score, means, trimmed


def main_v18() -> int:
    args = v1.parse_args()
    if args.self_test:
        v17.self_test_v17()
        sample = pd.DataFrame(
            {
                "symbol": ["BTCUSDT"] * 140,
                "direction": np.where(np.arange(140) % 2 == 0, 1, -1),
                "displacement_body_atr": np.linspace(0.2, 2.2, 140),
                "decision_time_ms": v1.utc_ms("2023-01-01") + np.arange(140) * v1.DAY_MS,
                "filled": np.arange(140) % 3 != 0,
                "resolved": True,
                "net_r": np.sin(np.arange(140) / 7),
                "label_end_time_ms": v1.utc_ms("2023-01-01") + (np.arange(140) + 1) * v1.DAY_MS,
                "exit_time_ms": v1.utc_ms("2023-01-01") + (np.arange(140) + 1) * v1.DAY_MS,
                "order_end_time_ms": v1.utc_ms("2023-01-01") + (np.arange(140) + 1) * v1.DAY_MS,
            }
        )
        eligible = pd.Series(True, index=sample.index)
        scores = prequential_scores_v18(
            sample,
            eligible,
            v1.utc_ms("2023-05-01"),
            v1.utc_ms("2023-06-01"),
            "monthly",
            min_train=20,
        )
        assert scores.notna().any()
        assert (scores.dropna().between(0, 1)).all()
        assert diversified_risk_multiplier(0.9, None, 0.5, 3.0) <= 2.0
        print("V18_DENSITY_ROBUST_SELF_TEST_PASS")
        return 0
    if args.data_root is None:
        raise SystemExit("--data-root is required")

    train_start = v1.utc_ms(args.train_start)
    train_end = v1.utc_ms(args.train_end_exclusive)
    eval_start = v1.utc_ms(args.evaluation_start)
    eval_end = v1.utc_ms(args.evaluation_end_exclusive)
    timeframes = (1, 3, 5, 15)
    minute_by_symbol: dict[str, pd.DataFrame] = {}
    setup_frames: dict[tuple[str, int], pd.DataFrame] = {}
    data_summary: dict[str, Any] = {}

    for symbol in args.symbols:
        bar_parts: list[pd.DataFrame] = []
        stream_parts: dict[str, list[pd.DataFrame]] = {
            name: []
            for name in ("open_interest", "account_ratio", "funding", "mark", "index", "premium")
        }
        for segment in [*args.train_segments, *args.evaluation_segments]:
            bars, streams = v1.load_segment(args.data_root, segment, symbol)
            bar_parts.append(bars)
            for name, stream in streams.items():
                stream_parts[name].append(stream)
        minute = v1.concatenate(bar_parts, "start_time_ms")
        minute = minute[
            (minute["start_time_ms"] >= train_start)
            & (minute["start_time_ms"] < eval_end)
        ].reset_index(drop=True)
        if minute.empty:
            raise v1.ResearchError(f"no data for {symbol}")
        streams = {
            name: v1.concatenate(parts, "available_at_ms")
            for name, parts in stream_parts.items()
        }
        minute_by_symbol[symbol] = minute
        data_summary[symbol] = {
            "rows_1m": len(minute),
            "first": v1.iso_ms(int(minute["start_time_ms"].iloc[0])),
            "last": v1.iso_ms(int(minute["start_time_ms"].iloc[-1])),
            "streams": {name: len(stream) for name, stream in streams.items()},
        }
        for timeframe in timeframes:
            setup_frames[(symbol, timeframe)] = v3.enrich_v3(
                v1.resample(minute, timeframe), timeframe, streams, minute
            )

    for timeframe in timeframes:
        mapping = {symbol: setup_frames[(symbol, timeframe)] for symbol in args.symbols}
        v1.add_smt(mapping)
        for symbol, frame in mapping.items():
            setup_frames[(symbol, timeframe)] = frame

    candidate_parts = [
        v1.raw_candidates(symbol, setup_frames[(symbol, timeframe)])
        for symbol in args.symbols
        for timeframe in timeframes
    ]
    candidate_parts = [part for part in candidate_parts if not part.empty]
    if not candidate_parts:
        raise v1.ResearchError("zero V18 SMC/ICT candidates")
    candidates = (
        pd.concat(candidate_parts, ignore_index=True, sort=False)
        .drop_duplicates("candidate_id")
        .sort_values("decision_time_ms", kind="stable")
        .reset_index(drop=True)
    )
    candidates = candidates[
        (candidates["decision_time_ms"] >= train_start)
        & (candidates["decision_time_ms"] < eval_end)
    ].reset_index(drop=True)

    grids = setup_grid_v18()
    geometry_paths: dict[float, pd.DataFrame] = {}
    for retrace in sorted({config.retrace for config in grids}):
        geometry = v1.SetupConfig(1, 0, 0, 0, retrace, False, False)
        records = [
            v1.simulate(
                row,
                minute_by_symbol[row["symbol"]],
                setup_frames[(row["symbol"], int(row["timeframe_min"]))],
                geometry,
                eval_end,
            )
            for row in candidates.to_dict("records")
        ]
        geometry_paths[retrace] = pd.DataFrame(records)

    trials: dict[float, pd.DataFrame] = {}
    for retrace, paths in geometry_paths.items():
        trial = candidates.merge(
            paths,
            on=["candidate_id", "symbol", "direction", "decision_time_ms"],
            how="left",
        )
        trial["label_end_time_ms"] = trial["exit_time_ms"].fillna(
            trial["order_end_time_ms"]
        )
        trials[retrace] = trial

    structural_results: list[dict[str, Any]] = []
    for config in grids:
        trial = trials[config.retrace]
        mask = v1.setup_mask(trial, config)
        resolved = (
            mask
            & trial["filled"].fillna(False)
            & trial["resolved"].fillna(False)
            & (trial["label_end_time_ms"] < train_end)
            & trial["net_r"].notna()
        )
        if int(resolved.sum()) < args.minimum_candidates:
            continue
        sample = trial.loc[resolved, ["decision_time_ms", "net_r"]]
        score, quarter_means, trimmed = structural_score(
            sample, train_start, train_end
        )
        structural_results.append(
            {
                "config": asdict(config),
                "key": config.key,
                "score": score,
                "count": int(len(sample)),
                "quarter_means": quarter_means,
                "top5_trimmed_mean_r": trimmed,
            }
        )
    if not structural_results:
        raise v1.ResearchError("no V18 structure survived chronological screening")
    structural_results.sort(key=lambda item: item["score"], reverse=True)

    prediction_start = train_start + 120 * v1.DAY_MS
    ml_results: list[dict[str, Any]] = []
    for screen in structural_results[:36]:
        config = v1.SetupConfig(**screen["config"])
        trial = trials[config.retrace].copy()
        eligible = v1.setup_mask(trial, config)
        for policy in ("monthly", "quarterly", "frozen"):
            scores = v1.prequential_scores(
                trial, eligible, prediction_start, train_end, policy
            )
            available = scores[
                eligible
                & (trial["decision_time_ms"] >= prediction_start)
                & (trial["decision_time_ms"] < train_end)
            ].dropna()
            if len(available) < 30:
                continue
            thresholds = sorted(
                {
                    float(available.quantile(quantile))
                    for quantile in (0.05, 0.15, 0.25, 0.40, 0.55, 0.70, 0.82, 0.90)
                }
            )
            trial["ml_score"] = scores
            for threshold in thresholds:
                metrics = v1.account_sim(
                    trial[eligible],
                    minute_by_symbol,
                    v1.AccountConfig(
                        risk_fraction=0.01,
                        leverage=10,
                        replacement_sigma=0.10,
                        confidence_risk_max=1.0,
                    ),
                    prediction_start,
                    train_end,
                    threshold,
                )
                if (
                    metrics["completed_trades"] < 25
                    or metrics["liquidation_events"]
                    or metrics["final_nav"] <= 0
                ):
                    continue
                ml_results.append(
                    {
                        "config": asdict(config),
                        "key": config.key,
                        "policy": policy,
                        "threshold": threshold,
                        "objective": robust_objective(metrics),
                        "metrics": compact(metrics),
                        "screen": screen,
                    }
                )
    if not ml_results:
        raise v1.ResearchError("no V18 decision-ready pre-2024 ML configuration")
    ml_results.sort(key=lambda item: item["objective"], reverse=True)
    selected = ml_results[0]
    config = v1.SetupConfig(**selected["config"])
    trial = trials[config.retrace].copy()
    eligible = v1.setup_mask(trial, config)
    trial["ml_score"] = v1.prequential_scores(
        trial, eligible, prediction_start, eval_end, selected["policy"]
    )

    pre = trial[eligible & (trial["decision_time_ms"] < train_end)]
    risk_results: list[dict[str, Any]] = []
    for account in account_grid_v18():
        metrics = v1.account_sim(
            pre,
            minute_by_symbol,
            account,
            prediction_start,
            train_end,
            float(selected["threshold"]),
        )
        if (
            metrics["completed_trades"] < 25
            or metrics["liquidation_events"]
            or metrics["final_nav"] <= 0
        ):
            continue
        risk_results.append(
            {
                "config": asdict(account),
                "key": account.key,
                "objective": robust_objective(metrics),
                "metrics": compact(metrics),
            }
        )
    if not risk_results:
        raise v1.ResearchError("V18 alpha failed robust account selection")
    risk_results.sort(key=lambda item: item["objective"], reverse=True)
    account = v1.AccountConfig(**risk_results[0]["config"])

    pre_metrics = v1.account_sim(
        pre,
        minute_by_symbol,
        account,
        prediction_start,
        train_end,
        float(selected["threshold"]),
    )
    evaluation = trial[
        eligible
        & (trial["decision_time_ms"] >= eval_start)
        & (trial["decision_time_ms"] < eval_end)
    ]
    evaluation_metrics = v1.account_sim(
        evaluation,
        minute_by_symbol,
        account,
        eval_start,
        eval_end,
        float(selected["threshold"]),
    )
    decision = (
        "ADVANCE_CONTINUOUS_CAUSAL_EVALUATION"
        if evaluation_metrics["completed_trades"] >= 40
        and not evaluation_metrics["liquidation_events"]
        and evaluation_metrics["final_nav"] > 0
        else "REVISE_DENSITY_OR_CORE_SYSTEMIZATION"
    )
    summary = {
        "schema_version": 18,
        "system_id": "SYS-SWIPALNAM-LIQUIDITY-DELIVERY-ML-V18-DENSITY-ROBUST",
        "decision": decision,
        "target_hit": bool(evaluation_metrics["geometric_daily_growth"] >= 0.01),
        "fixed_latency_ms": v1.LATENCY_MS,
        "timeframes_min": list(timeframes),
        "symbols": list(args.symbols),
        "data": data_summary,
        "periods": {
            "train_start": args.train_start,
            "train_end_exclusive": args.train_end_exclusive,
            "evaluation_start": args.evaluation_start,
            "evaluation_end_exclusive": args.evaluation_end_exclusive,
        },
        "candidate_count": len(candidates),
        "configuration_count": len(grids),
        "configuration_screen_survivors": len(structural_results),
        "selected_structural_configuration": asdict(config),
        "selected_structural_key": config.key,
        "selected_retraining_policy": selected["policy"],
        "selected_ml_score_threshold": selected["threshold"],
        "selected_account_configuration": asdict(account),
        "selected_account_key": account.key,
        "pre2024_metrics": compact(pre_metrics),
        "evaluation_metrics": compact(evaluation_metrics),
        "provisional_2024h1_metrics": compact(evaluation_metrics)
        if eval_end <= v1.utc_ms("2024-07-01T00:00:00Z")
        else None,
        "full_period_metrics": compact(evaluation_metrics)
        if eval_end > v1.utc_ms("2024-07-01T00:00:00Z")
        else None,
        "top_structural_screens": structural_results[:36],
        "top_ml_alternatives": ml_results[:24],
        "top_account_alternatives": risk_results[:24],
        "selection_contract": {
            "signal_source": "dual-auction SMC/ICT only",
            "model_window_policy": {
                "monthly": "rolling 210 days",
                "quarterly": "rolling 420 days",
                "frozen": "all resolved pre-cutoff history",
            },
            "execution_score": "fill-adjusted conditional net-R per expected global-slot occupancy",
            "concentration_control": "pre-2024 objective includes top-1/top-5 removed growth, profit HHI and monthly breadth",
            "risk_allocation": "bounded smooth confidence multiplier; base risk remains selected from pre-2024 account paths",
            "no_elapsed_time_forced_exit": True,
        },
        "causality_notes": [
            "all liquidity levels and pivots require confirmation before decision",
            "rolling feature columns are selected only from observations available at each cutoff",
            "labels enter training only after their order or position outcome is resolved",
            "orders activate after fixed 500 ms",
            "one global pending or live position slot across all symbols",
            "evaluation-boundary fills and exits remain hidden",
            "open positions at a boundary are marked to executable liquidation value",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    v1.write_json(args.output / "RUN_SUMMARY.json", summary)
    pd.DataFrame(pre_metrics["trades"]).to_csv(
        args.output / "PRE2024_TRADES.csv", index=False
    )
    pd.DataFrame(evaluation_metrics["trades"]).to_csv(
        args.output / "EVALUATION_TRADES.csv", index=False
    )
    pd.DataFrame(pre_metrics["daily_nav"]).to_csv(
        args.output / "PRE2024_DAILY_NAV.csv", index=False
    )
    pd.DataFrame(evaluation_metrics["daily_nav"]).to_csv(
        args.output / "EVALUATION_DAILY_NAV.csv", index=False
    )
    print(
        json.dumps(
            {
                "decision": decision,
                "target_hit": summary["target_hit"],
                "candidate_count": len(candidates),
                "pre2024": compact(pre_metrics),
                "evaluation": compact(evaluation_metrics),
                "structural_key": config.key,
                "account_key": account.key,
            },
            ensure_ascii=False,
            indent=2,
            default=v1.json_default,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main_v18())
