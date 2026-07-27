#!/usr/bin/env python3
"""V15: dual-auction SMC/ICT with causal fill-adjusted ML and exact NAV.

The signal ontology has two transcript-grounded families:
1. external-liquidity raid -> reclaim/displacement/MSS -> FVG/OB mitigation;
2. decisive BOS/displacement -> first FVG/OB mitigation -> next external liquidity.

Both families share one global pending/position slot, fixed 500 ms activation,
structural invalidation, opposing-liquidity delivery and causal model updates.
ML ranks pre-existing price-action candidates; it never creates a signal.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import liquidity_delivery_ml_v11_regime_features as v11  # noqa: E402

v10 = v11.v10
v9 = v10.v9
v8 = v9.v8
v7 = v8.v7
v6 = v7.v6
v5 = v7.v5
v4 = v5.v4
v3 = v11.v3
v1 = v11.v1

_BASE_RAW = v1.raw_candidates


# ---------------------------------------------------------------------------
# Causal, stable ML feature and model semantics
# ---------------------------------------------------------------------------

def causal_feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["symbol_code"] = work["symbol"].map(
        {"BTCUSDT": 0, "ETHUSDT": 1, "SOLUSDT": 2, "XRPUSDT": 3}
    )
    for name in v1.FEATURES:
        if name not in work:
            work[name] = np.nan
    # HGBT learns missing-value routing natively.  Whole-frame medians would
    # let an earlier decision depend on the future evaluation distribution.
    return work[v1.FEATURES].replace([np.inf, -np.inf], np.nan).astype(float)


def causal_model_pair(seed: int) -> tuple[HistGradientBoostingClassifier, HistGradientBoostingRegressor]:
    return (
        HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=160,
            max_leaf_nodes=15,
            min_samples_leaf=20,
            l2_regularization=0.8,
            random_state=seed,
        ),
        HistGradientBoostingRegressor(
            loss="absolute_error",
            learning_rate=0.045,
            max_iter=160,
            max_leaf_nodes=15,
            min_samples_leaf=20,
            l2_regularization=1.0,
            random_state=seed + 1,
        ),
    )


def fill_adjusted_prequential_scores(
    frame: pd.DataFrame,
    eligible: pd.Series,
    start_ms: int,
    end_ms: int,
    policy: str,
    min_train: int = 50,
) -> pd.Series:
    """Causal execution expectancy including the global-slot fill probability."""
    scores = pd.Series(np.nan, index=frame.index, dtype=float)
    x = causal_feature_matrix(frame)
    if policy == "frozen":
        cutoffs, windows = [start_ms], [(start_ms, end_ms)]
    else:
        freq = "MS" if policy == "monthly" else "QS"
        dates = list(
            pd.date_range(
                pd.Timestamp(start_ms, unit="ms", tz="UTC"),
                pd.Timestamp(end_ms, unit="ms", tz="UTC"),
                freq=freq,
                inclusive="left",
            )
        )
        cutoffs = [start_ms] + [
            int(ts.value // 1_000_000)
            for ts in dates
            if int(ts.value // 1_000_000) > start_ms
        ]
        windows = [
            (cutoff, cutoffs[i + 1] if i + 1 < len(cutoffs) else end_ms)
            for i, cutoff in enumerate(cutoffs)
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
        if int(resolved.sum()) < min_train or int(outcome_train.sum()) < min_train or not predict.any():
            continue

        fill_y = frame.loc[resolved, "filled"].astype(int)
        y = frame.loc[outcome_train, "net_r"].astype(float).clip(-8, 12)
        binary = (y > 0).astype(int)
        if binary.nunique() < 2:
            continue

        seed = 7 + int(cutoff // v1.DAY_MS) % 997
        outcome_classifier, outcome_regressor = causal_model_pair(seed)
        outcome_classifier.fit(x.loc[outcome_train], binary)
        outcome_regressor.fit(x.loc[outcome_train], y)
        win_probability = outcome_classifier.predict_proba(x.loc[predict])[:, 1]
        conditional_r = outcome_regressor.predict(x.loc[predict])

        if fill_y.nunique() >= 2:
            fill_classifier = HistGradientBoostingClassifier(
                learning_rate=0.05,
                max_iter=140,
                max_leaf_nodes=15,
                min_samples_leaf=20,
                l2_regularization=0.8,
                random_state=seed + 2,
            )
            fill_classifier.fit(x.loc[resolved], fill_y)
            fill_probability = fill_classifier.predict_proba(x.loc[predict])[:, 1]
        else:
            fill_probability = np.full(int(predict.sum()), float(fill_y.mean()))

        conditional_quality = conditional_r * (0.55 + win_probability) + 0.2 * (win_probability - 0.5)
        # An unfilled resting order consumes the sole global slot.  The small
        # explicit opportunity penalty prevents attractive-but-unfillable
        # geometry from dominating the ranking.
        scores.loc[predict] = fill_probability * conditional_quality - (1.0 - fill_probability) * 0.05
    return scores


v1.feature_matrix = causal_feature_matrix
v1.model_pair = causal_model_pair
v1.prequential_scores = fill_adjusted_prequential_scores


# ---------------------------------------------------------------------------
# Causal pending replacement and confidence-conditioned risk
# ---------------------------------------------------------------------------

def chosen_candidates_causal(
    frame: pd.DataFrame,
    threshold: float,
    replacement_sigma: float,
) -> pd.DataFrame:
    eligible = (
        frame[frame["ml_score"].notna() & (frame["ml_score"] >= threshold)]
        .sort_values(["decision_time_ms", "ml_score"], ascending=[True, False])
        .drop_duplicates("decision_time_ms")
        .reset_index(drop=True)
    )
    if eligible.empty:
        return eligible
    margin = float(replacement_sigma) * max(abs(float(threshold)), 0.10)
    active: pd.Series | None = None
    chosen: list[dict[str, Any]] = []
    for _, row in eligible.iterrows():
        decision = int(row["decision_time_ms"])
        if active is None:
            active = row
            continue
        if bool(active["filled"]):
            entry = int(active["entry_time_ms"])
            exit_time = int(active["exit_time_ms"])
            if decision >= exit_time:
                chosen.append(active.to_dict())
                active = row
                continue
            if decision >= entry:
                continue
        elif decision >= int(active["order_end_time_ms"]):
            active = row
            continue
        if float(row["ml_score"]) > float(active["ml_score"]) + margin:
            active = row
    if active is not None and bool(active["filled"]):
        chosen.append(active.to_dict())
    if not chosen:
        return eligible.iloc[0:0].copy()
    return pd.DataFrame(chosen).sort_values("decision_time_ms", kind="stable").reset_index(drop=True)


def causal_risk_multiplier(score: float, frame: Any, threshold: float, maximum: float) -> float:
    denominator = max(abs(float(threshold)), 0.10)
    normalized = float(np.clip((score - float(threshold)) / denominator, 0.0, 1.0))
    return 0.35 + (float(maximum) - 0.35) * normalized**1.5


v6._chosen_filled_candidates = chosen_candidates_causal
v7._risk_multiplier = causal_risk_multiplier
v5._risk_multiplier = causal_risk_multiplier


# ---------------------------------------------------------------------------
# Realistic cost, sizing and UTC-midnight NAV account engine
# ---------------------------------------------------------------------------

def turnover_window_causal(minute: pd.DataFrame, timestamp_ms: int, bars: int = 60) -> float:
    available = minute["available_at_ms"].to_numpy(np.int64)
    pos = int(np.searchsorted(available, timestamp_ms, side="right"))
    return float(minute["turnover"].iloc[max(0, pos - bars):pos].sum())


def impact_rate_uncapped(notional: float, local_turnover: float, impact_bps: float) -> float:
    participation = notional / max(local_turnover, v1.EPS)
    return float(impact_bps) * math.sqrt(max(participation, 0.0)) / 10_000


def account_sim_exact_causal(
    frame: pd.DataFrame,
    minute_by_symbol: Mapping[str, pd.DataFrame],
    account: Any,
    start_ms: int,
    end_ms: int,
    threshold: float,
    initial_nav: float = 10_000.0,
) -> dict[str, Any]:
    selected = (
        frame[frame["ml_score"].notna() & (frame["ml_score"] >= threshold)]
        .sort_values(["decision_time_ms", "ml_score"], ascending=[True, False])
        .drop_duplicates("decision_time_ms")
    )
    nav = initial_nav
    slot_free = start_ms
    trades: list[dict[str, Any]] = []
    skips = 0
    liquidation_events = 0
    fee_rate = float(account.taker_fee_bps) / 10_000
    embedded_slippage = float(account.slippage_bps) / 10_000

    for row in selected.itertuples(index=False):
        decision = int(row.decision_time_ms)
        if not (start_ms <= decision < end_ms):
            continue
        if decision < slot_free:
            skips += 1
            continue
        if not bool(row.filled):
            slot_free = min(int(row.order_end_time_ms), end_ms)
            continue

        direction = int(row.direction)
        entry = float(row.entry_price)
        stop_quote = float(row.stop_price)
        stop_exec = stop_quote * (1 - direction * embedded_slippage)
        stop_distance = abs(entry - stop_exec)
        planned_loss = nav * float(account.risk_fraction)
        if hasattr(account, "confidence_risk_max"):
            planned_loss *= causal_risk_multiplier(
                float(row.ml_score),
                frame,
                threshold,
                float(account.confidence_risk_max),
            )
        minute = minute_by_symbol[str(row.symbol)]
        local_turnover = turnover_window_causal(minute, int(row.entry_time_ms))
        max_quantity = nav * float(account.leverage) / entry
        quantity = min(
            planned_loss / max(stop_distance + (entry + stop_exec) * fee_rate, v1.EPS),
            max_quantity,
        )
        # Fixed point: planned loss, quantity and participation-sensitive impact
        # must agree rather than sizing from a fictitious full-leverage order.
        for _ in range(18):
            provisional_notional = quantity * entry
            provisional_impact = impact_rate_uncapped(
                provisional_notional, local_turnover, float(account.impact_bps)
            )
            expected_loss_per_unit = stop_distance + (entry + stop_exec) * (
                fee_rate + provisional_impact
            )
            solved = min(
                planned_loss / max(expected_loss_per_unit, v1.EPS),
                max_quantity,
            )
            if abs(solved - quantity) <= max(1e-12, quantity * 1e-8):
                quantity = solved
                break
            quantity = 0.5 * quantity + 0.5 * solved
        if quantity <= 0:
            continue

        notional = quantity * entry
        entry_impact = impact_rate_uncapped(
            notional, local_turnover, float(account.impact_bps)
        )
        effective_leverage = notional / max(nav, v1.EPS)
        stop_pct = stop_distance / entry
        liquidation_distance = max(
            0.0,
            1 / max(effective_leverage, v1.EPS)
            - float(account.maintenance_margin_rate)
            - 2 * fee_rate,
        )
        if stop_pct >= 0.90 * liquidation_distance:
            liquidation_events += 1
            continue

        partial_time, tp1 = v5._partial_event(row, minute)
        partial_fraction = 0.40 if partial_time is not None else 0.0
        remaining_fraction = 1.0 - partial_fraction
        exit_price = float(row.exit_price)
        exit_turnover = turnover_window_causal(minute, int(row.exit_time_ms))
        exit_impact = impact_rate_uncapped(
            quantity * remaining_fraction * exit_price,
            exit_turnover,
            float(account.impact_bps),
        )
        partial_impact = (
            impact_rate_uncapped(
                quantity * partial_fraction * tp1,
                turnover_window_causal(minute, int(partial_time)),
                float(account.impact_bps),
            )
            if partial_time is not None
            else 0.0
        )

        gross = quantity * float(row.gross_pnl_per_unit)
        entry_cost = quantity * entry * (fee_rate + entry_impact)
        # The path simulator does not embed adverse execution in the partial TP.
        partial_cost = quantity * partial_fraction * tp1 * (
            fee_rate + embedded_slippage + partial_impact
        )
        final_cost = quantity * remaining_fraction * exit_price * (
            fee_rate + exit_impact
        )
        funding_rate = float(row.funding) if np.isfinite(float(row.funding)) else 0.0
        holding_days = max(
            0.0,
            (int(row.exit_time_ms) - int(row.entry_time_ms)) / v1.DAY_MS,
        )
        funding_cost = direction * notional * funding_rate * holding_days * 3.0
        pnl = gross - entry_cost - partial_cost - final_cost - funding_cost
        before = nav
        nav += pnl
        trades.append(
            {
                "candidate_id": row.candidate_id,
                "symbol": row.symbol,
                "direction": direction,
                "decision_time_ms": decision,
                "entry_time_ms": int(row.entry_time_ms),
                "exit_time_ms": int(row.exit_time_ms),
                "entry_time": v1.iso_ms(int(row.entry_time_ms)),
                "exit_time": v1.iso_ms(int(row.exit_time_ms)),
                "exit_reason": row.exit_reason,
                "entry_price": entry,
                "exit_price": exit_price,
                "stop_price": stop_quote,
                "target_price": float(row.target_price),
                "partial_time_ms": partial_time,
                "partial_time": v1.iso_ms(partial_time),
                "partial_price": tp1 if partial_time is not None else None,
                "partial_fraction": partial_fraction,
                "remaining_fraction": remaining_fraction,
                "quantity": quantity,
                "notional": notional,
                "effective_leverage": effective_leverage,
                "planned_loss": planned_loss,
                "gross_pnl": gross,
                "entry_cost": entry_cost,
                "partial_cost": partial_cost,
                "final_cost": final_cost,
                "funding_cost": funding_cost,
                "net_pnl": pnl,
                "realized_r": pnl / max(planned_loss, v1.EPS),
                "nav_before": before,
                "nav_after": nav,
                "ml_score": float(row.ml_score),
                "funding_snapshot": funding_rate,
                "entry_impact_rate": entry_impact,
                "exit_impact_rate": exit_impact,
            }
        )
        slot_free = min(int(row.exit_time_ms), end_ms)
        if nav <= 0:
            liquidation_events += 1
            nav = 0.0
            break

    day_starts = np.arange(start_ms, end_ms, v1.DAY_MS, dtype=np.int64)
    daily_values: list[float] = []
    trade_cursor = 0
    realized_nav = initial_nav
    for day_start in day_starts:
        boundary = int(day_start + v1.DAY_MS)
        while trade_cursor < len(trades) and int(trades[trade_cursor]["exit_time_ms"]) < boundary:
            realized_nav = float(trades[trade_cursor]["nav_after"])
            trade_cursor += 1
        equity = realized_nav
        if trade_cursor < len(trades):
            trade = trades[trade_cursor]
            if int(trade["entry_time_ms"]) < boundary <= int(trade["exit_time_ms"]):
                minute = minute_by_symbol[str(trade["symbol"])]
                mark = v5._mark_close(minute, boundary)
                direction = int(trade["direction"])
                partial_done = (
                    trade["partial_time_ms"] is not None
                    and int(trade["partial_time_ms"]) < boundary
                )
                partial_fraction = 0.40 if partial_done else 0.0
                remaining_fraction = 1.0 - partial_fraction
                quantity = float(trade["quantity"])
                notional_remaining = quantity * remaining_fraction * mark
                liquidation_impact = impact_rate_uncapped(
                    notional_remaining,
                    turnover_window_causal(minute, boundary),
                    float(account.impact_bps),
                )
                executable_mark = mark * (
                    1 - direction * (embedded_slippage + liquidation_impact)
                )
                unrealized = quantity * remaining_fraction * (
                    executable_mark - float(trade["entry_price"])
                ) * direction
                partial_realized = (
                    quantity
                    * partial_fraction
                    * (float(trade["partial_price"]) - float(trade["entry_price"]))
                    * direction
                    if partial_done
                    else 0.0
                )
                partial_cost = float(trade["partial_cost"]) if partial_done else 0.0
                hypothetical_exit_cost = (
                    quantity * remaining_fraction * executable_mark * fee_rate
                )
                elapsed_days = max(
                    0.0,
                    (boundary - int(trade["entry_time_ms"])) / v1.DAY_MS,
                )
                accrued_funding = (
                    direction
                    * float(trade["notional"])
                    * float(trade["funding_snapshot"])
                    * elapsed_days
                    * 3.0
                )
                equity = (
                    float(trade["nav_before"])
                    + partial_realized
                    + unrealized
                    - float(trade["entry_cost"])
                    - partial_cost
                    - hypothetical_exit_cost
                    - accrued_funding
                )
        daily_values.append(max(float(equity), 0.0))

    daily = pd.Series(
        daily_values,
        index=pd.to_datetime(day_starts, unit="ms", utc=True),
        dtype=float,
    )
    path = (
        pd.concat(
            [
                pd.Series(
                    [initial_nav],
                    index=[daily.index[0] - pd.Timedelta(days=1)],
                ),
                daily,
            ]
        )
        if len(daily)
        else pd.Series([initial_nav], dtype=float)
    )
    pnl_values = np.array([float(trade["net_pnl"]) for trade in trades], dtype=float)
    positive = float(pnl_values[pnl_values > 0].sum()) if len(pnl_values) else 0.0
    negative = float(-pnl_values[pnl_values < 0].sum()) if len(pnl_values) else 0.0
    positive_only = np.maximum(pnl_values, 0)
    top_share = (
        float(np.sort(positive_only)[-5:].sum() / positive_only.sum())
        if len(positive_only) and positive_only.sum() > 0
        else None
    )
    final_nav = float(daily.iloc[-1]) if len(daily) else nav
    return {
        "initial_nav": initial_nav,
        "final_nav": final_nav,
        "account_multiple": final_nav / initial_nav,
        "geometric_daily_growth": v1.geometric_growth(path),
        "max_drawdown": v1.drawdown(path),
        "completed_trades": len(trades),
        "win_rate": float(np.mean(pnl_values > 0)) if len(pnl_values) else None,
        "profit_factor": float(positive / negative) if negative > 0 else None,
        "top_5_pnl_share": top_share,
        "liquidation_events": liquidation_events,
        "slot_skips": skips,
        "daily_nav": [
            {"time": ts.isoformat(), "nav": float(value)}
            for ts, value in daily.items()
        ],
        "trades": trades,
        "daily_nav_method": "UTC midnight executable liquidation value with uncapped participation impact",
        "embedded_execution_slippage_bps_per_side": float(account.slippage_bps),
    }


v5._turnover_window = turnover_window_causal
v5._impact_rate = impact_rate_uncapped
v5.account_sim_exact = account_sim_exact_causal


# ---------------------------------------------------------------------------
# Second structural family: displacement/BOS -> first mitigation continuation
# ---------------------------------------------------------------------------

CONTINUATION_FEATURES = [
    "break_extension_atr",
    "prior_compression_atr",
    "ob_age_bars",
]
for feature in CONTINUATION_FEATURES:
    if feature not in v1.FEATURES:
        v1.FEATURES.append(feature)


def _level_confluence(row: pd.Series, direction: int, level: float, tolerance: float) -> int:
    names = (
        [
            "last_swing_high",
            "equal_high_level",
            "opening_range_high",
            "prev_4h_high",
            "prev_session_high",
            "prev_day_high",
            "prev_week_high",
        ]
        if direction > 0
        else [
            "last_swing_low",
            "equal_low_level",
            "opening_range_low",
            "prev_4h_low",
            "prev_session_low",
            "prev_day_low",
            "prev_week_low",
        ]
    )
    return sum(
        int(np.isfinite(float(row.get(name, np.nan))) and abs(float(row.get(name)) - level) <= tolerance)
        for name in names
    )


def continuation_candidates(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or len(frame) < 30:
        return pd.DataFrame()
    close = frame["close"].to_numpy(float)
    open_ = frame["open"].to_numpy(float)
    high = frame["high"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    atr = frame["atr"].to_numpy(float)
    body_atr = frame["body_atr"].to_numpy(float)
    range_atr = frame["range_atr"].to_numpy(float)
    location = frame["close_location"].to_numpy(float)
    internal_high = frame["internal_high"].to_numpy(float)
    internal_low = frame["internal_low"].to_numpy(float)
    signed = frame["body_signed"].to_numpy(float)

    prior_long_unbroken = np.r_[False, close[:-1] <= internal_high[:-1]]
    prior_short_unbroken = np.r_[False, close[:-1] >= internal_low[:-1]]
    valid = np.isfinite(atr) & (atr > 0) & np.isfinite(body_atr) & np.isfinite(range_atr)
    long_events = np.flatnonzero(
        valid
        & (signed > 0)
        & (close > internal_high)
        & prior_long_unbroken
        & (body_atr >= 0.35)
        & (range_atr >= 0.65)
        & (location >= 0.58)
    )
    short_events = np.flatnonzero(
        valid
        & (signed < 0)
        & (close < internal_low)
        & prior_short_unbroken
        & (body_atr >= 0.35)
        & (range_atr >= 0.65)
        & (location <= 0.42)
    )

    rows: list[dict[str, Any]] = []
    timeframe = int(frame["timeframe_min"].iloc[0])
    for direction, indices in ((1, long_events), (-1, short_events)):
        for i in indices:
            if i < 2:
                continue
            row = frame.iloc[int(i)]
            break_level = float(internal_high[i] if direction > 0 else internal_low[i])
            extension = (float(close[i]) - break_level) * direction / max(float(atr[i]), v1.EPS)
            if not np.isfinite(extension) or extension <= 0:
                continue

            if direction > 0:
                gap_low, gap_high = float(high[i - 2]), float(low[i])
            else:
                gap_low, gap_high = float(high[i]), float(low[i - 2])
            gap = gap_high - gap_low
            if gap <= 0:
                gap_low, gap_high = sorted((float(open_[i]), float(close[i])))
                fvg_atr = 0.0
            else:
                fvg_atr = gap / max(float(atr[i]), v1.EPS)

            ob_i = max(0, int(i) - 1)
            for j in range(int(i) - 1, max(-1, int(i) - 11), -1):
                opposite = close[j] < open_[j] if direction > 0 else close[j] > open_[j]
                if opposite:
                    ob_i = j
                    break
            if direction > 0:
                ob_low, ob_high = float(low[ob_i]), float(max(open_[ob_i], close[ob_i]))
            else:
                ob_low, ob_high = float(min(open_[ob_i], close[ob_i])), float(high[ob_i])
            overlap_low, overlap_high = max(ob_low, gap_low), min(ob_high, gap_high)
            overlap = overlap_high > overlap_low
            zone_low, zone_high = (
                (overlap_low, overlap_high)
                if overlap
                else (min(ob_low, gap_low), max(ob_high, gap_high))
            )
            if not (
                np.isfinite(zone_low)
                and np.isfinite(zone_high)
                and zone_high > zone_low > 0
            ):
                continue
            reference = (zone_low + zone_high) / 2
            recent = slice(max(0, int(i) - 10), int(i) + 1)
            stop_anchor = (
                min(ob_low, float(np.min(low[recent])))
                if direction > 0
                else max(ob_high, float(np.max(high[recent])))
            )
            risk = abs(reference - stop_anchor)
            if risk <= 0:
                continue
            target = v4._target_from_known_liquidity(
                row, row, direction, reference, risk
            )
            rr = (target - reference) * direction / risk
            if not np.isfinite(rr) or rr < 1.0:
                continue

            compression_slice = slice(max(0, int(i) - 6), int(i))
            compression = (
                float(np.max(high[compression_slice]) - np.min(low[compression_slice]))
                / max(float(atr[i]), v1.EPS)
                if int(i) > 0
                else np.nan
            )
            tolerance = max(float(atr[i]) * 0.12, float(close[i]) * 0.0003)
            confluence = _level_confluence(row, direction, break_level, tolerance)
            pd4 = float(row.get("pd_4h", np.nan))
            pd_ok = (
                bool(
                    (direction > 0 and pd4 <= 0.58)
                    or (direction < 0 and pd4 >= 0.42)
                )
                if np.isfinite(pd4)
                else False
            )
            candidate: dict[str, Any] = {
                "candidate_id": f"{symbol}-CONT{timeframe}-{int(row['start_time_ms'])}-{direction:+d}",
                "symbol": symbol,
                "direction": direction,
                "timeframe_min": timeframe,
                "decision_time_ms": int(row["available_at_ms"]),
                "swept_level_name": "confirmed_internal_BOS",
                "swept_level": break_level,
                "sweep_depth_atr": extension,
                "sweep_wick_atr": float(
                    (high[i] - close[i] if direction > 0 else close[i] - low[i])
                    / max(float(atr[i]), v1.EPS)
                ),
                "liquidity_confluence": confluence,
                "displacement_body_atr": float(body_atr[i]),
                "displacement_range_atr": float(range_atr[i]),
                "close_location": float(location[i]),
                "fvg_low": float(gap_low),
                "fvg_high": float(gap_high),
                "fvg_atr": float(fvg_atr),
                "ob_low": ob_low,
                "ob_high": ob_high,
                "zone_low": zone_low,
                "zone_high": zone_high,
                "fvg_ob_overlap": float(overlap),
                "stop_anchor": stop_anchor,
                "target_price": target,
                "structural_rr": rr,
                "atr": float(atr[i]),
                "atr_pct": float(row.get("atr_pct", np.nan)),
                "volume_z": float(row.get("volume_z", np.nan)),
                "turnover_z": float(row.get("turnover_z", np.nan)),
                "trend_1h": float(row.get("trend_1h", np.nan)),
                "trend_4h": float(row.get("trend_4h", np.nan)),
                "pd_1h": float(row.get("pd_1h", np.nan)),
                "pd_4h": pd4,
                "pd_aligned": float(pd_ok),
                "oi_change_z": float(row.get("oi_change_z", np.nan)),
                "account_ratio_z": float(row.get("account_ratio_z", np.nan)),
                "basis_bps": float(row.get("basis_bps", np.nan)),
                "funding": float(row.get("funding", np.nan)),
                "smt_bull": float(row.get("smt_bull", 0)),
                "smt_bear": float(row.get("smt_bear", 0)),
                "session_bucket": float(row.get("session_bucket", np.nan)),
                "hour_sin": float(row.get("hour_sin", np.nan)),
                "hour_cos": float(row.get("hour_cos", np.nan)),
                "dow_sin": float(row.get("dow_sin", np.nan)),
                "dow_cos": float(row.get("dow_cos", np.nan)),
                "model_family": 2.0,
                "context_timeframe": float(timeframe),
                "sweep_to_mss_bars": 0.0,
                "htf_sweep_age_min": 0.0,
                "break_extension_atr": extension,
                "prior_compression_atr": compression,
                "ob_age_bars": float(int(i) - ob_i),
            }
            for feature in v11.REGIME_FEATURES[:13]:
                candidate[feature] = float(row.get(feature, np.nan))
            candidate["directional_crowding"] = direction * float(
                row.get("crowding_composite", np.nan)
            )
            trend_1h = float(row.get("trend_1h", np.nan))
            trend_4h = float(row.get("trend_4h", np.nan))
            candidate["directional_trend_alignment"] = direction * (
                (trend_1h if np.isfinite(trend_1h) else 0.0)
                + (trend_4h if np.isfinite(trend_4h) else 0.0)
            )
            candidate["directional_smt"] = float(
                row.get("smt_bull", 0)
                if direction > 0
                else row.get("smt_bear", 0)
            )
            rows.append(candidate)
    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .drop_duplicates("candidate_id")
        .sort_values("decision_time_ms", kind="stable")
        .reset_index(drop=True)
    )


def raw_dual_auction(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    sweep_reversal = _BASE_RAW(symbol, frame)
    continuation = continuation_candidates(symbol, frame)
    parts = [
        part
        for part in (sweep_reversal, continuation)
        if part is not None and not part.empty
    ]
    if not parts:
        return pd.DataFrame()
    return (
        pd.concat(parts, ignore_index=True, sort=False)
        .drop_duplicates("candidate_id")
        .sort_values("decision_time_ms", kind="stable")
        .reset_index(drop=True)
    )


v1.raw_candidates = raw_dual_auction


def self_test_v15() -> None:
    v1.self_test()
    sample = pd.DataFrame(
        {
            "symbol": ["BTCUSDT"] * 100,
            "direction": np.where(np.arange(100) % 2 == 0, 1, -1),
            "displacement_body_atr": np.linspace(0.2, 2.0, 100),
        }
    )
    x = causal_feature_matrix(sample)
    assert x.isna().any().any()
    classifier, regressor = causal_model_pair(31)
    classifier.fit(x, pd.Series(np.arange(100) % 2))
    regressor.fit(x, pd.Series(np.sin(np.arange(100) / 8)))
    assert np.isfinite(classifier.predict_proba(x.iloc[:3])).all()
    assert np.isfinite(regressor.predict(x.iloc[:3])).all()
    assert impact_rate_uncapped(400, 100, 4) > impact_rate_uncapped(100, 100, 4)
    bars = pd.DataFrame(
        {"available_at_ms": [1_000, 2_000], "turnover": [10.0, 1_000_000.0]}
    )
    assert turnover_window_causal(bars, 1_500) == 10.0
    assert causal_risk_multiplier(0.4, None, 0.2, 2.0) == causal_risk_multiplier(
        0.4, object(), 0.2, 2.0
    )
    print("V15_DUAL_AUCTION_SELF_TEST_PASS")


def main() -> int:
    if "--self-test" in sys.argv:
        self_test_v15()
        return 0
    return v3.main_v3()


if __name__ == "__main__":
    raise SystemExit(main())
