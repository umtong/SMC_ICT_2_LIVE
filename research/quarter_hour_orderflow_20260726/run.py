from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

import source

CLAIM_ID = "CLM-20260726-0240-QHOUR-001"
TRAIN_DATES = ("2022-01-01", "2022-03-01", "2022-05-01")
CALIBRATION_DATES = ("2022-07-01",)
CONFIRMATION_DATES = ("2022-09-01", "2022-11-01")
ALL_DATES = TRAIN_DATES + CALIBRATION_DATES + CONFIRMATION_DATES
SYMBOLS = source.SYMBOLS
DECISION_COST_BPS = 18.0
MIN_EXPECTED_EDGE_BPS = 5.0
ROUNDTRIP_COSTS_BPS = (12.0, 18.0, 24.0)
TAIL_DAYS = 3
PLANNED_RISK_FRACTION = 0.01
MAXIMUM_LEVERAGE = 5.0
MAXIMUM_PRIOR_MINUTE_QUOTE_PARTICIPATION = 0.001

FEATURE_COLUMNS = [
    "phase_quarter",
    "mode_reversal",
    "symbol_btc",
    "symbol_eth",
    "symbol_sol",
    "symbol_xrp",
    "flow_imbalance",
    "abs_flow_imbalance",
    "opening_return",
    "route_aligned_opening_return",
    "opening_range_bps",
    "log_total_notional",
    "log_trade_count",
    "log_activity_ratio",
    "pre_return_5m",
    "pre_return_15m",
    "pre_return_60m",
    "realized_volatility_60m",
    "atr_15m_bps",
    "contract_taker_imbalance_15m",
    "oi_change_15m",
    "log_taker_long_short_ratio",
    "log_toptrader_long_short_ratio",
    "reward_bps",
    "loss_bps",
    "reward_risk",
    "hour_sin",
    "hour_cos",
]


@dataclass(frozen=True, slots=True)
class PathOutcome:
    status: str
    exit_ms: int | None
    exit_price: float | None
    gross_return: float | None
    funding_fraction: float | None
    last_available_ms: int


def safe_log_ratio(new: float, old: float) -> float:
    if not (math.isfinite(new) and math.isfinite(old) and new > 0 and old > 0):
        return math.nan
    return math.log(new / old)


def _valid_rows(frame: pd.DataFrame, end_exclusive: int, count: int) -> pd.DataFrame:
    subset = frame[(frame.index < end_exclusive) & frame["valid"]]
    return subset.tail(count)


def _metric_features(metrics: pd.DataFrame, event_start_ms: int) -> tuple[float, float, float]:
    available = metrics[metrics.index < event_start_ms]
    if available.empty:
        return math.nan, math.nan, math.nan
    current = available.iloc[-1]
    previous_candidates = available[available.index <= event_start_ms - 15 * source.MINUTE_MS]
    previous = previous_candidates.iloc[-1] if not previous_candidates.empty else available.iloc[0]
    oi_change = safe_log_ratio(float(current.open_interest), float(previous.open_interest))
    taker_ratio = float(current.taker_long_short_ratio)
    top_ratio = float(current.toptrader_long_short_ratio)
    return oi_change, math.log(taker_ratio), math.log(top_ratio)


def _funding_fraction(
    funding: pd.DataFrame,
    mark: pd.DataFrame,
    entry_ms: int,
    exit_ms: int,
    side: int,
    entry_price: float,
) -> float:
    events = funding[(funding.index > entry_ms) & (funding.index <= exit_ms)]
    total = 0.0
    for timestamp, row in events.iterrows():
        if timestamp in mark.index and bool(mark.at[timestamp, "valid"]):
            mark_price = float(mark.at[timestamp, "open"])
        else:
            prior = mark[(mark.index <= timestamp) & mark["valid"]]
            if prior.empty:
                raise ValueError(f"missing causal mark for funding timestamp {timestamp}")
            mark_price = float(prior.iloc[-1].open)
        total += -float(side) * float(row.funding_rate) * (mark_price / entry_price)
    return total


def resolve_path(
    contract: pd.DataFrame,
    mark: pd.DataFrame,
    funding: pd.DataFrame,
    *,
    entry_ms: int,
    side: int,
    entry_price: float,
    stop_price: float,
    target_price: float,
) -> PathOutcome:
    future = contract[(contract.index >= entry_ms) & contract["valid"]]
    if future.empty:
        return PathOutcome("unresolved", None, None, None, None, int(contract.index.max()))
    last_available_ms = int(future.index.max())
    for timestamp, row in future.iterrows():
        open_price = float(row.open)
        high = float(row.high)
        low = float(row.low)
        if side > 0:
            if open_price <= stop_price:
                exit_price, status = open_price, "stop"
            elif open_price >= target_price:
                exit_price, status = target_price, "target"
            elif low <= stop_price and high >= target_price:
                exit_price, status = stop_price, "stop"
            elif low <= stop_price:
                exit_price, status = stop_price, "stop"
            elif high >= target_price:
                exit_price, status = target_price, "target"
            else:
                continue
        else:
            if open_price >= stop_price:
                exit_price, status = open_price, "stop"
            elif open_price <= target_price:
                exit_price, status = target_price, "target"
            elif high >= stop_price and low <= target_price:
                exit_price, status = stop_price, "stop"
            elif high >= stop_price:
                exit_price, status = stop_price, "stop"
            elif low <= target_price:
                exit_price, status = target_price, "target"
            else:
                continue
        exit_ms = int(timestamp)
        gross_return = float(side) * (float(exit_price) / entry_price - 1.0)
        funding_fraction = _funding_fraction(
            funding, mark, entry_ms, exit_ms, side, entry_price
        )
        return PathOutcome(
            status=status,
            exit_ms=exit_ms,
            exit_price=float(exit_price),
            gross_return=gross_return,
            funding_fraction=funding_fraction,
            last_available_ms=last_available_ms,
        )
    return PathOutcome("unresolved", None, None, None, None, last_available_ms)


def _target_stop(
    *,
    side: int,
    mode: str,
    entry_price: float,
    event_high: float,
    event_low: float,
    prior_15m_high: float,
    prior_15m_low: float,
    prior_240m_high: float,
    prior_240m_low: float,
    atr_15m_abs: float,
) -> tuple[float, float]:
    target = prior_240m_high if side > 0 else prior_240m_low
    if mode == "continuation":
        stop = prior_15m_low if side > 0 else prior_15m_high
    elif mode == "reversal":
        buffer = max(0.10 * atr_15m_abs, 0.0002 * entry_price)
        stop = event_low - buffer if side > 0 else event_high + buffer
    else:
        raise ValueError(mode)
    return float(target), float(stop)


def build_candidates(bundle: source.DayBundle) -> list[dict]:
    output: list[dict] = []
    activity_history: dict[str, list[float]] = {"quarter": [], "control": []}
    windows = bundle.windows.sort_values("event_start_ms")
    for event in windows.itertuples(index=False):
        phase = str(event.phase)
        prior_activity = activity_history[phase]
        activity_ratio = (
            float(event.total_notional) / float(np.median(prior_activity[-24:]))
            if bool(event.valid) and len(prior_activity) >= 8 and np.median(prior_activity[-24:]) > 0
            else math.nan
        )
        if bool(event.valid) and float(event.total_notional) > 0:
            prior_activity.append(float(event.total_notional))
        if not bool(event.valid):
            continue

        event_start_ms = int(event.event_start_ms)
        entry_ms = event_start_ms + source.MINUTE_MS
        if entry_ms not in bundle.contract.index or not bool(bundle.contract.at[entry_ms, "valid"]):
            continue
        prior_240 = _valid_rows(bundle.contract, event_start_ms, 240)
        if len(prior_240) < 240:
            continue
        prior_60 = prior_240.tail(60)
        prior_15 = prior_240.tail(15)
        prior_5 = prior_240.tail(5)
        entry_price = float(bundle.contract.at[entry_ms, "open"])
        prior_quote_volume = float(prior_240.iloc[-1].quote_volume)
        if not (math.isfinite(prior_quote_volume) and prior_quote_volume > 0):
            continue

        closes_61 = prior_240.close.tail(61).to_numpy(float)
        log_returns = np.diff(np.log(closes_61))
        realized_volatility_60m = float(np.sqrt(np.square(log_returns).sum()))
        atr_15m_abs = float((prior_15.high - prior_15.low).mean())
        atr_15m_bps = 10_000.0 * atr_15m_abs / entry_price
        pre_return_5m = safe_log_ratio(float(prior_5.iloc[-1].close), float(prior_5.iloc[0].open))
        pre_return_15m = safe_log_ratio(float(prior_15.iloc[-1].close), float(prior_15.iloc[0].open))
        pre_return_60m = safe_log_ratio(float(prior_60.iloc[-1].close), float(prior_60.iloc[0].open))
        quote_total_15m = float(prior_15.quote_volume.sum())
        taker_buy_15m = float(prior_15.taker_buy_quote.sum())
        contract_taker_imbalance_15m = (
            2.0 * taker_buy_15m / quote_total_15m - 1.0 if quote_total_15m > 0 else math.nan
        )
        oi_change_15m, log_taker_ratio, log_top_ratio = _metric_features(
            bundle.metrics, event_start_ms
        )
        flow_imbalance = float(event.imbalance)
        if not math.isfinite(flow_imbalance) or abs(flow_imbalance) < 0.02:
            continue
        flow_side = 1 if flow_imbalance > 0 else -1
        hour = (event_start_ms // 3_600_000) % 24
        base = {
            "date": bundle.date,
            "symbol": bundle.symbol,
            "phase": phase,
            "event_start_ms": event_start_ms,
            "decision_ms": int(event.decision_ms),
            "entry_ms": entry_ms,
            "entry_price": entry_price,
            "prior_quote_volume": prior_quote_volume,
            "phase_quarter": 1.0 if phase == "quarter" else 0.0,
            "symbol_btc": 1.0 if bundle.symbol == "BTCUSDT" else 0.0,
            "symbol_eth": 1.0 if bundle.symbol == "ETHUSDT" else 0.0,
            "symbol_sol": 1.0 if bundle.symbol == "SOLUSDT" else 0.0,
            "symbol_xrp": 1.0 if bundle.symbol == "XRPUSDT" else 0.0,
            "flow_imbalance": flow_imbalance,
            "abs_flow_imbalance": abs(flow_imbalance),
            "opening_return": float(event.opening_return),
            "opening_range_bps": float(event.opening_range_bps),
            "log_total_notional": math.log1p(float(event.total_notional)),
            "log_trade_count": math.log1p(int(event.trade_count)),
            "log_activity_ratio": math.log(activity_ratio) if math.isfinite(activity_ratio) and activity_ratio > 0 else math.nan,
            "pre_return_5m": pre_return_5m,
            "pre_return_15m": pre_return_15m,
            "pre_return_60m": pre_return_60m,
            "realized_volatility_60m": realized_volatility_60m,
            "atr_15m_bps": atr_15m_bps,
            "contract_taker_imbalance_15m": contract_taker_imbalance_15m,
            "oi_change_15m": oi_change_15m,
            "log_taker_long_short_ratio": log_taker_ratio,
            "log_toptrader_long_short_ratio": log_top_ratio,
            "hour_sin": math.sin(2.0 * math.pi * hour / 24.0),
            "hour_cos": math.cos(2.0 * math.pi * hour / 24.0),
        }
        prior_15m_high = float(prior_15.high.max())
        prior_15m_low = float(prior_15.low.min())
        prior_240m_high = float(prior_240.high.max())
        prior_240m_low = float(prior_240.low.min())

        for mode, side in (("continuation", flow_side), ("reversal", -flow_side)):
            target_price, stop_price = _target_stop(
                side=side,
                mode=mode,
                entry_price=entry_price,
                event_high=float(event.high_price),
                event_low=float(event.low_price),
                prior_15m_high=prior_15m_high,
                prior_15m_low=prior_15m_low,
                prior_240m_high=prior_240m_high,
                prior_240m_low=prior_240m_low,
                atr_15m_abs=atr_15m_abs,
            )
            if side > 0 and not (stop_price < entry_price < target_price):
                continue
            if side < 0 and not (target_price < entry_price < stop_price):
                continue
            reward_bps = 10_000.0 * abs(target_price / entry_price - 1.0)
            loss_bps = 10_000.0 * abs(stop_price / entry_price - 1.0)
            if not (30.0 <= reward_bps <= 2_000.0 and 5.0 <= loss_bps <= 1_000.0):
                continue
            reward_risk = reward_bps / loss_bps
            if reward_risk < 0.50:
                continue
            outcome = resolve_path(
                bundle.contract,
                bundle.mark,
                bundle.funding,
                entry_ms=entry_ms,
                side=side,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
            )
            route_aligned = float(side) * float(event.opening_return)
            candidate_id = (
                f"{bundle.date}|{event_start_ms}|{bundle.symbol}|{phase}|{mode}|{side:+d}"
            )
            row = dict(base)
            row.update({
                "candidate_id": candidate_id,
                "mode": mode,
                "side": side,
                "mode_reversal": 1.0 if mode == "reversal" else 0.0,
                "route_aligned_opening_return": route_aligned,
                "target_price": target_price,
                "stop_price": stop_price,
                "reward_bps": reward_bps,
                "loss_bps": loss_bps,
                "reward_risk": reward_risk,
                "outcome_status": outcome.status,
                "label_target_first": 1 if outcome.status == "target" else 0,
                "exit_ms": outcome.exit_ms,
                "exit_price": outcome.exit_price,
                "gross_return": outcome.gross_return,
                "funding_fraction": outcome.funding_fraction,
                "last_available_ms": outcome.last_available_ms,
            })
            output.append(row)
    return output


def feature_matrix(frame: pd.DataFrame, medians: pd.Series | None = None) -> tuple[np.ndarray, pd.Series]:
    values = frame[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).astype(float)
    if medians is None:
        medians = values.median(axis=0).fillna(0.0)
    filled = values.fillna(medians).fillna(0.0)
    return filled.to_numpy(float), medians


def safe_auc(y_true: np.ndarray, score: np.ndarray) -> float | None:
    if len(np.unique(y_true)) < 2:
        return None
    return float(roc_auc_score(y_true, score))


def fit_and_score(candidates: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    train = candidates[candidates.date.isin(TRAIN_DATES)].copy()
    calibration = candidates[candidates.date.isin(CALIBRATION_DATES)].copy()
    confirmation = candidates[candidates.date.isin(CONFIRMATION_DATES)].copy()
    if min(len(train), len(calibration), len(confirmation)) == 0:
        raise ValueError("empty chronological ML partition")
    x_train, medians = feature_matrix(train)
    x_cal, _ = feature_matrix(calibration, medians)
    x_all, _ = feature_matrix(candidates, medians)
    y_train = train.label_target_first.to_numpy(int)
    y_cal = calibration.label_target_first.to_numpy(int)
    if len(np.unique(y_train)) < 2:
        raise ValueError("training target has one class")

    model = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=240,
        max_leaf_nodes=15,
        max_depth=4,
        min_samples_leaf=30,
        l2_regularization=2.0,
        random_state=20260726,
    )
    model.fit(x_train, y_train)
    raw_cal = model.predict_proba(x_cal)[:, 1]
    raw_all = model.predict_proba(x_all)[:, 1]
    if len(np.unique(y_cal)) >= 2 and len(np.unique(raw_cal)) >= 3:
        calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)
        calibrator.fit(raw_cal, y_cal)
        calibrated_all = np.asarray(calibrator.predict(raw_all), dtype=float)
        calibration_method = "isotonic"
    else:
        calibrated_all = np.clip(raw_all, 0.001, 0.999)
        calibration_method = "identity_fallback"
    scored = candidates.copy()
    scored["raw_probability"] = raw_all
    scored["target_probability"] = calibrated_all
    scored["expected_edge_bps_18"] = (
        scored.target_probability * scored.reward_bps
        - (1.0 - scored.target_probability) * scored.loss_bps
        - DECISION_COST_BPS
    )

    confirmation_scored = scored[scored.date.isin(CONFIRMATION_DATES)]
    y_confirm = confirmation_scored.label_target_first.to_numpy(int)
    p_confirm = confirmation_scored.target_probability.to_numpy(float)
    raw_confirm = confirmation_scored.raw_probability.to_numpy(float)
    train_prevalence = float(y_train.mean())
    brier = float(brier_score_loss(y_confirm, p_confirm))
    null_brier = float(np.mean(np.square(y_confirm - train_prevalence)))
    baseline_score = confirmation_scored.route_aligned_opening_return.to_numpy(float)
    metrics = {
        "model": "HistGradientBoostingClassifier_plus_isotonic",
        "feature_count": len(FEATURE_COLUMNS),
        "train_rows": len(train),
        "calibration_rows": len(calibration),
        "confirmation_rows": len(confirmation),
        "train_target_prevalence": train_prevalence,
        "calibration_method": calibration_method,
        "confirmation_auc_calibrated": safe_auc(y_confirm, p_confirm),
        "confirmation_auc_raw": safe_auc(y_confirm, raw_confirm),
        "confirmation_auc_structural_baseline": safe_auc(y_confirm, baseline_score),
        "confirmation_brier": brier,
        "confirmation_null_brier": null_brier,
        "confirmation_brier_skill": 1.0 - brier / null_brier if null_brier > 0 else None,
    }
    return scored, metrics


def max_drawdown(nav_path: Iterable[float]) -> float:
    peak = -math.inf
    maximum = 0.0
    for value in nav_path:
        peak = max(peak, value)
        if peak > 0:
            maximum = max(maximum, 1.0 - value / peak)
    return maximum


def simulate_account(
    scored: pd.DataFrame,
    *,
    phase: str,
    cost_bps: float,
    dates: tuple[str, ...],
    banned_candidate_ids: set[str] | None = None,
) -> dict:
    banned = banned_candidate_ids or set()
    eligible = scored[
        scored.date.isin(dates)
        & (scored.phase == phase)
        & (scored.expected_edge_bps_18 >= MIN_EXPECTED_EDGE_BPS)
        & (~scored.candidate_id.isin(banned))
    ].copy()
    eligible = eligible.sort_values(
        ["entry_ms", "expected_edge_bps_18", "reward_risk", "candidate_id"],
        ascending=[True, False, False, True],
    )
    nav = 10_000.0
    nav_values = [nav]
    busy_until = -1
    trades: list[dict] = []
    unresolved_selected = 0
    capacity_rejections = 0
    terminal = False
    for entry_ms, group in eligible.groupby("entry_ms", sort=True):
        entry_ms = int(entry_ms)
        if entry_ms < busy_until or terminal:
            continue
        candidate = group.iloc[0]
        if candidate.outcome_status == "unresolved" or pd.isna(candidate.exit_ms):
            unresolved_selected += 1
            busy_until = int(candidate.last_available_ms) + source.MINUTE_MS
            trades.append({
                "candidate_id": candidate.candidate_id,
                "date": candidate.date,
                "symbol": candidate.symbol,
                "mode": candidate.mode,
                "side": int(candidate.side),
                "entry_ms": entry_ms,
                "exit_ms": None,
                "status": "unresolved",
                "expected_edge_bps_18": float(candidate.expected_edge_bps_18),
                "nav_before": nav,
                "notional": 0.0,
                "pnl": None,
                "nav_after": nav,
            })
            continue
        per_notional_loss = (
            float(candidate.loss_bps) / 10_000.0
            + cost_bps / 10_000.0
            + 0.0005
        )
        risk_notional = nav * PLANNED_RISK_FRACTION / per_notional_loss
        leverage_notional = nav * MAXIMUM_LEVERAGE
        capacity_notional = (
            float(candidate.prior_quote_volume) * MAXIMUM_PRIOR_MINUTE_QUOTE_PARTICIPATION
        )
        notional = min(risk_notional, leverage_notional, capacity_notional)
        if not math.isfinite(notional) or notional < 10.0:
            capacity_rejections += 1
            continue
        gross_fraction = float(candidate.gross_return)
        funding_fraction = float(candidate.funding_fraction)
        net_fraction = gross_fraction + funding_fraction - cost_bps / 10_000.0
        pnl = notional * net_fraction
        nav_before = nav
        nav += pnl
        nav_values.append(nav)
        busy_until = int(candidate.exit_ms)
        trades.append({
            "candidate_id": candidate.candidate_id,
            "date": candidate.date,
            "symbol": candidate.symbol,
            "mode": candidate.mode,
            "side": int(candidate.side),
            "entry_ms": entry_ms,
            "exit_ms": int(candidate.exit_ms),
            "status": candidate.outcome_status,
            "expected_edge_bps_18": float(candidate.expected_edge_bps_18),
            "target_probability": float(candidate.target_probability),
            "reward_bps": float(candidate.reward_bps),
            "loss_bps": float(candidate.loss_bps),
            "gross_fraction": gross_fraction,
            "funding_fraction": funding_fraction,
            "cost_fraction": cost_bps / 10_000.0,
            "nav_before": nav_before,
            "notional": notional,
            "pnl": pnl,
            "nav_after": nav,
        })
        if nav <= 0:
            nav = 0.0
            nav_values[-1] = 0.0
            terminal = True

    completed = [trade for trade in trades if trade["status"] != "unresolved"]
    profits = [float(trade["pnl"]) for trade in completed if float(trade["pnl"]) > 0]
    losses = [-float(trade["pnl"]) for trade in completed if float(trade["pnl"]) < 0]
    top_five_share = (
        sum(sorted(profits, reverse=True)[:5]) / sum(profits) if profits else None
    )
    day_returns: dict[str, float] = {}
    for date in dates:
        date_trades = [trade for trade in completed if trade["date"] == date]
        if not date_trades:
            day_returns[date] = 0.0
        else:
            day_returns[date] = (
                float(date_trades[-1]["nav_after"]) / float(date_trades[0]["nav_before"]) - 1.0
            )
    median_trade = (
        float(np.median([trade["pnl"] / trade["nav_before"] for trade in completed]))
        if completed else None
    )
    return {
        "phase": phase,
        "cost_bps": cost_bps,
        "starting_nav": 10_000.0,
        "ending_nav": nav,
        "total_return": nav / 10_000.0 - 1.0,
        "completed_trades": len(completed),
        "unresolved_selected": unresolved_selected,
        "capacity_rejections": capacity_rejections,
        "profit_factor": sum(profits) / sum(losses) if losses else None,
        "maximum_drawdown": max_drawdown(nav_values),
        "median_trade_nav_return": median_trade,
        "top_five_positive_pnl_share": top_five_share,
        "positive_day_fraction": sum(value > 0 for value in day_returns.values()) / len(dates),
        "day_returns": day_returns,
        "terminal_loss": terminal,
        "trades": trades,
    }


def winner_removal_stress(scored: pd.DataFrame, base: dict, dates: tuple[str, ...]) -> dict:
    completed = [trade for trade in base["trades"] if trade["status"] != "unresolved"]
    remove_count = int(math.ceil(0.10 * len(completed))) if completed else 0
    winners = sorted(
        (trade for trade in completed if float(trade["pnl"]) > 0),
        key=lambda item: float(item["pnl"]),
        reverse=True,
    )[:remove_count]
    banned = {str(trade["candidate_id"]) for trade in winners}
    stressed = simulate_account(
        scored,
        phase="quarter",
        cost_bps=24.0,
        dates=dates,
        banned_candidate_ids=banned,
    )
    stressed["removed_count"] = len(banned)
    stressed["removed_candidate_ids"] = sorted(banned)
    return stressed


def gate_result(model_metrics: dict, paths: dict, control: dict, removal: dict) -> dict:
    primary_12 = paths["12"]
    primary_24 = paths["24"]
    checks = {
        "confirmation_auc_at_least_0_52": (
            model_metrics["confirmation_auc_calibrated"] is not None
            and model_metrics["confirmation_auc_calibrated"] >= 0.52
        ),
        "positive_brier_skill": (
            model_metrics["confirmation_brier_skill"] is not None
            and model_metrics["confirmation_brier_skill"] > 0
        ),
        "minimum_20_completed_trades_at_24bp": primary_24["completed_trades"] >= 20,
        "positive_total_return_at_12bp": primary_12["total_return"] > 0,
        "positive_total_return_at_24bp": primary_24["total_return"] > 0,
        "zero_selected_unresolved_paths": primary_24["unresolved_selected"] == 0,
        "positive_after_exact_top_10pct_winner_removal": removal["total_return"] > 0,
        "minimum_positive_day_fraction_0_5": primary_24["positive_day_fraction"] >= 0.5,
        "quarter_hour_exceeds_matched_control_at_24bp": primary_24["total_return"] > control["total_return"],
        "maximum_drawdown_at_most_35pct": primary_24["maximum_drawdown"] <= 0.35,
        "top_five_positive_pnl_share_at_most_65pct": (
            primary_24["top_five_positive_pnl_share"] is not None
            and primary_24["top_five_positive_pnl_share"] <= 0.65
        ),
        "no_terminal_loss": not primary_24["terminal_loss"],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "decision": "OPEN_2022_SECONDARY_CONFIRMATION" if all(checks.values()) else "RETIRE_EXACT_INFORMATION_UNIT",
    }


def summarize_candidates(candidates: pd.DataFrame) -> dict:
    summary: dict[str, dict] = {}
    for split, dates in (
        ("train", TRAIN_DATES),
        ("calibration", CALIBRATION_DATES),
        ("confirmation", CONFIRMATION_DATES),
    ):
        frame = candidates[candidates.date.isin(dates)]
        summary[split] = {
            "rows": len(frame),
            "quarter_rows": int((frame.phase == "quarter").sum()),
            "control_rows": int((frame.phase == "control").sum()),
            "target_rate": float(frame.label_target_first.mean()) if len(frame) else None,
            "unresolved_rate": float((frame.outcome_status == "unresolved").mean()) if len(frame) else None,
            "by_symbol": {str(key): int(value) for key, value in frame.groupby("symbol").size().items()},
            "by_mode": {str(key): int(value) for key, value in frame.groupby("mode").size().items()},
        }
    return summary


def run(output: Path, cache: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    bundles, records = source.load_bundles(ALL_DATES, SYMBOLS, cache, tail_days=TAIL_DAYS)
    candidate_rows: list[dict] = []
    for bundle in bundles:
        rows = build_candidates(bundle)
        candidate_rows.extend(rows)
        print(f"candidates {bundle.date} {bundle.symbol}: {len(rows)}", flush=True)
    candidates = pd.DataFrame(candidate_rows)
    if candidates.empty:
        raise ValueError("zero structurally valid candidates")
    missing = [column for column in FEATURE_COLUMNS if column not in candidates]
    if missing:
        raise ValueError(f"missing features: {missing}")
    scored, model_metrics = fit_and_score(candidates)
    confirmation = scored[scored.date.isin(CONFIRMATION_DATES)].copy()
    paths = {
        str(int(cost)): simulate_account(
            confirmation,
            phase="quarter",
            cost_bps=cost,
            dates=CONFIRMATION_DATES,
        )
        for cost in ROUNDTRIP_COSTS_BPS
    }
    control = simulate_account(
        confirmation,
        phase="control",
        cost_bps=24.0,
        dates=CONFIRMATION_DATES,
    )
    removal = winner_removal_stress(confirmation, paths["24"], CONFIRMATION_DATES)
    gate = gate_result(model_metrics, paths, control, removal)
    manifest = source.source_manifest(records)
    result = {
        "schema_version": 2,
        "claim_id": CLAIM_ID,
        "result_id": "RES-20260726-ML-QHOUR-STRUCTURAL-FATAL-001",
        "stage": "PRE2024_FATAL_SCREEN_NOT_RANK_ELIGIBLE",
        "information_cutoff": "2023-12-31",
        "market_dates_opened": list(ALL_DATES),
        "symbols": list(SYMBOLS),
        "source_manifest": manifest,
        "candidate_summary": summarize_candidates(scored),
        "model_metrics": model_metrics,
        "decision_rule": {
            "model": "one pooled HGBT plus one isotonic map",
            "minimum_expected_edge_bps_after_18bp": MIN_EXPECTED_EDGE_BPS,
            "entry": "next exact one-minute contract open after the completed ten-second window",
            "exit": "pre-known structural target or structural stop only; adverse same-minute ordering",
            "elapsed_time_liquidation": False,
            "one_global_slot": True,
        },
        "confirmation_account_paths": paths,
        "matched_control_24bp": control,
        "winner_removal_24bp": removal,
        "fatal_gate": gate,
        "opened_2022_secondary_confirmation": False,
        "opened_2023": False,
        "opened_2024": False,
        "opened_2025_2026": False,
        "credentials_used": False,
        "orders_submitted": False,
        "live_permission": False,
    }
    result_path = output / "RESULT.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    (output / "RESULT.sha256").write_text(
        f"{hashlib.sha256(result_path.read_bytes()).hexdigest()}  RESULT.json\n",
        encoding="utf-8",
    )
    confirmation_columns = [
        "candidate_id", "date", "symbol", "phase", "mode", "side", "entry_ms", "exit_ms",
        "outcome_status", "reward_bps", "loss_bps", "raw_probability", "target_probability",
        "expected_edge_bps_18", "gross_return", "funding_fraction",
    ]
    scored[confirmation_columns].to_csv(output / "SCORED_CANDIDATES.csv", index=False)
    print(json.dumps({
        "gate": gate,
        "model_metrics": model_metrics,
        "path_24bp": {key: value for key, value in paths["24"].items() if key != "trades"},
        "control_24bp": {key: value for key, value in control.items() if key != "trades"},
    }, indent=2, sort_keys=True, allow_nan=False), flush=True)
    return result


def self_test(output: Path) -> None:
    index = np.array([0, 60_000, 120_000], dtype=np.int64)
    contract = pd.DataFrame({
        "open": [100.0, 100.0, 100.0],
        "high": [101.0, 103.0, 104.0],
        "low": [99.0, 98.0, 99.0],
        "close": [100.0, 101.0, 103.0],
        "quote_volume": [1_000_000.0] * 3,
        "taker_buy_quote": [500_000.0] * 3,
        "valid": [True] * 3,
    }, index=index)
    mark = contract[["open", "high", "low", "close", "valid"]].copy()
    funding = pd.DataFrame({"funding_rate": []}, index=pd.Index([], dtype=np.int64))
    adverse = resolve_path(
        contract, mark, funding, entry_ms=0, side=1, entry_price=100.0,
        stop_price=99.0, target_price=101.0,
    )
    assert adverse.status == "stop", adverse
    target = resolve_path(
        contract.iloc[1:], mark.iloc[1:], funding, entry_ms=60_000, side=1,
        entry_price=100.0, stop_price=97.0, target_price=102.0,
    )
    assert target.status == "target", target
    assert source.normalize_timestamp_ms("2022-01-01 00:00:00") == 1_640_995_200_000
    output.mkdir(parents=True, exist_ok=True)
    (output / "SELF_TEST.txt").write_text("passed\n", encoding="utf-8")
    print("quarter-hour structural ML self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test(args.output)
        return 0
    run(args.output, args.cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
