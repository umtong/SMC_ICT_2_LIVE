from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import run_screen as core

ROOT = Path(__file__).resolve().parent
PREREG_PATH = ROOT / "preregistration.json"
AMENDMENT_PATH = ROOT / "amendment_001_ml_core.json"
FEATURE_NAMES = (
    "symbol_eth",
    "gap_kind_nwog",
    "gap_signed_atr",
    "residual_in_gap_direction",
    "response_in_gap_direction_atr",
    "rebalance_progress",
    "response_body_efficiency",
    "response_wick_support",
    "log_volume_ratio",
    "pretrend_in_gap_direction_atr",
    "log_continuation_to_rebalance_distance",
)
MODEL_ID = "CME_GAP_COMPETING_RISK_LOGIT_V1"
POLICY_ID = hashlib.sha256(MODEL_ID.encode()).hexdigest()[:20]
DECISION_BARS = 2
DECISION_COST_BPS = 18.0
MAX_ABS_ROLL_RESIDUAL_BPS = 35.0
MIN_GAP_ATR = 0.15
TRAIN_END = pd.Timestamp("2021-08-31T23:59:59Z")
FIT_HOLDOUT_START = pd.Timestamp("2021-09-01T00:00:00Z")
STAGE_BOUNDS = {
    "fit_holdout": (FIT_HOLDOUT_START, pd.Timestamp("2021-12-31T23:59:59Z")),
    "development": (pd.Timestamp("2022-01-01T00:00:00Z"), pd.Timestamp("2022-12-31T23:59:59Z")),
    "confirmation": (pd.Timestamp("2023-01-01T00:00:00Z"), pd.Timestamp("2023-12-31T23:59:59Z")),
}
COSTS = (12, 18, 24)


@dataclass(frozen=True, slots=True)
class Opportunity:
    symbol: str
    gap_kind: str
    trading_date: str
    event_open_ts: pd.Timestamp
    entry_ts: pd.Timestamp
    direction: int
    entry_price: float
    rebalance_level: float
    continuation_level: float
    feature_values: tuple[float, ...]
    continuation_label: int | None
    resolution: str
    resolution_ts: pd.Timestamp | None


@dataclass(frozen=True, slots=True)
class RoutedSetup:
    opportunity: Opportunity
    probability_continuation: float
    expected_value_continuation_bps: float
    expected_value_rebalance_bps: float
    selected_expected_value_bps: float
    selected_route: str
    setup: core.Setup


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def exact_row(frame: pd.DataFrame, timestamp: pd.Timestamp) -> pd.Series | None:
    if timestamp not in frame.index:
        return None
    row = frame.loc[timestamp]
    return row.iloc[-1] if isinstance(row, pd.DataFrame) else row


def nearest_continuation_level(event: core.GapEvent, entry_price: float, direction: int) -> float | None:
    if direction > 0:
        candidates = [
            level for level in (event.previous_day_high, event.previous_week_high)
            if math.isfinite(float(level)) and float(level) > entry_price
        ]
        return min(candidates) if candidates else None
    candidates = [
        level for level in (event.previous_day_low, event.previous_week_low)
        if math.isfinite(float(level)) and float(level) < entry_price
    ]
    return max(candidates) if candidates else None


def barrier_hits(row: pd.Series, direction: int, continuation: float, rebalance: float) -> tuple[bool, bool]:
    high = float(row["high"])
    low = float(row["low"])
    if direction > 0:
        return high >= continuation, low <= rebalance
    return low <= continuation, high >= rebalance


def first_touch_label(
    bars: pd.DataFrame,
    entry_ts: pd.Timestamp,
    direction: int,
    continuation: float,
    rebalance: float,
) -> tuple[int | None, str, pd.Timestamp | None]:
    start = int(bars.index.searchsorted(entry_ts, side="left"))
    if start >= len(bars) or bars.index[start] != entry_ts:
        return None, "entry_bar_missing", None
    for position in range(start, len(bars)):
        row = bars.iloc[position]
        cont_hit, reb_hit = barrier_hits(row, direction, continuation, rebalance)
        timestamp = bars.index[position]
        if cont_hit and reb_hit:
            return None, "ambiguous_same_bar", timestamp
        if cont_hit:
            return 1, "continuation_first", timestamp
        if reb_hit:
            return 0, "rebalance_first", timestamp
    return None, "censored_at_stage_end", None


def build_opportunity(event: core.GapEvent, bars: pd.DataFrame) -> Opportunity | None:
    direction = 1 if event.gap_return_bps > 0 else -1 if event.gap_return_bps < 0 else 0
    if direction == 0 or abs(event.roll_residual_bps) > MAX_ABS_ROLL_RESIDUAL_BPS:
        return None
    gap_distance = abs(event.execution_open - event.mapped_prior_close)
    if not math.isfinite(gap_distance) or gap_distance <= 0 or gap_distance / event.atr < MIN_GAP_ATR:
        return None

    decision_rows: list[pd.Series] = []
    for offset in range(DECISION_BARS):
        row = exact_row(bars, event.open_ts + pd.Timedelta(minutes=15 * offset))
        if row is None:
            return None
        decision_rows.append(row)
    entry_ts = event.open_ts + pd.Timedelta(minutes=15 * DECISION_BARS)
    entry_row = exact_row(bars, entry_ts)
    if entry_row is None:
        return None
    entry_price = float(entry_row["open"])
    rebalance = float(event.mapped_prior_close)
    continuation = nearest_continuation_level(event, entry_price, direction)
    if continuation is None:
        return None
    if direction * (entry_price - rebalance) <= 0 or direction * (continuation - entry_price) <= 0:
        return None

    aggregate_open = float(decision_rows[0]["open"])
    aggregate_close = float(decision_rows[-1]["close"])
    aggregate_high = max(float(row["high"]) for row in decision_rows)
    aggregate_low = min(float(row["low"]) for row in decision_rows)
    aggregate_range = max(aggregate_high - aggregate_low, np.finfo(float).eps)
    if direction > 0:
        pre_resolved = aggregate_high >= continuation or aggregate_low <= rebalance
    else:
        pre_resolved = aggregate_low <= continuation or aggregate_high >= rebalance
    if pre_resolved:
        return None

    open_position = int(bars.index.searchsorted(event.open_ts, side="left"))
    if open_position < core.ATR_BARS:
        return None
    prior = bars.iloc[open_position - core.ATR_BARS:open_position]
    prior_volume = pd.to_numeric(prior["quote_volume"], errors="coerce").dropna()
    if prior_volume.empty:
        return None
    median_volume = float(prior_volume.median())
    response_volume = sum(float(row["quote_volume"]) for row in decision_rows)
    historical_price = float(prior.iloc[0]["close"])

    upper_wick = aggregate_high - max(aggregate_open, aggregate_close)
    lower_wick = min(aggregate_open, aggregate_close) - aggregate_low
    rebalance_distance = abs(math.log(rebalance / entry_price)) * 10_000.0
    continuation_distance = abs(math.log(continuation / entry_price)) * 10_000.0
    if min(rebalance_distance, continuation_distance) <= 0:
        return None

    features = (
        1.0 if event.symbol == "ETHUSDT" else 0.0,
        1.0 if event.gap_kind == "NWOG" else 0.0,
        (event.execution_open - event.mapped_prior_close) / event.atr,
        direction * event.roll_residual_bps / max(abs(event.gap_return_bps), 1.0),
        direction * (aggregate_close - event.execution_open) / event.atr,
        direction * (event.execution_open - aggregate_close) / gap_distance,
        direction * (aggregate_close - aggregate_open) / aggregate_range,
        direction * (lower_wick - upper_wick) / aggregate_range,
        math.log((response_volume + 1.0) / (DECISION_BARS * median_volume + 1.0)),
        direction * (event.execution_open - historical_price) / event.atr,
        math.log(continuation_distance / rebalance_distance),
    )
    if len(features) != len(FEATURE_NAMES) or not np.isfinite(np.asarray(features, dtype=float)).all():
        return None

    label, resolution, resolution_ts = first_touch_label(
        bars, entry_ts, direction, continuation, rebalance
    )
    return Opportunity(
        symbol=event.symbol,
        gap_kind=event.gap_kind,
        trading_date=event.trading_date,
        event_open_ts=event.open_ts,
        entry_ts=entry_ts,
        direction=direction,
        entry_price=entry_price,
        rebalance_level=rebalance,
        continuation_level=continuation,
        feature_values=tuple(float(value) for value in features),
        continuation_label=label,
        resolution=resolution,
        resolution_ts=resolution_ts,
    )


def build_opportunities(
    cme_by_symbol: dict[str, pd.DataFrame],
    bars_by_symbol: dict[str, pd.DataFrame],
) -> list[Opportunity]:
    opportunities: list[Opportunity] = []
    for cme_symbol, cme in cme_by_symbol.items():
        symbol = core.CME_TO_EXECUTION[cme_symbol]
        events = core.build_gap_events(cme_symbol, cme, bars_by_symbol[symbol])
        for event in events:
            opportunity = build_opportunity(event, bars_by_symbol[symbol])
            if opportunity is not None:
                opportunities.append(opportunity)
    opportunities.sort(key=lambda item: (item.entry_ts, item.symbol, item.trading_date))
    return opportunities


def labeled(opportunities: Iterable[Opportunity]) -> list[Opportunity]:
    return [item for item in opportunities if item.continuation_label in (0, 1)]


def fit_model(opportunities: list[Opportunity]) -> Pipeline:
    rows = labeled(opportunities)
    if len(rows) < 40:
        raise RuntimeError(f"insufficient labeled training events: {len(rows)}")
    labels = np.asarray([int(item.continuation_label) for item in rows], dtype=int)
    if len(np.unique(labels)) != 2:
        raise RuntimeError("training labels contain only one competing-risk class")
    matrix = np.asarray([item.feature_values for item in rows], dtype=float)
    model = Pipeline([
        ("scale", StandardScaler()),
        ("logit", LogisticRegression(
            C=0.25,
            penalty="l2",
            solver="lbfgs",
            max_iter=5000,
            random_state=0,
        )),
    ])
    model.fit(matrix, labels)
    return model


def continuation_probability(model: Pipeline, opportunity: Opportunity) -> float:
    probabilities = model.predict_proba(np.asarray([opportunity.feature_values], dtype=float))[0]
    classes = list(model.named_steps["logit"].classes_)
    return float(probabilities[classes.index(1)])


def model_diagnostics(model: Pipeline, opportunities: list[Opportunity]) -> dict[str, Any]:
    rows = labeled(opportunities)
    if not rows:
        return {
            "labeled_count": 0,
            "continuation_count": 0,
            "rebalance_count": 0,
            "roc_auc": None,
            "average_precision": None,
            "brier_score": None,
        }
    matrix = np.asarray([item.feature_values for item in rows], dtype=float)
    labels = np.asarray([int(item.continuation_label) for item in rows], dtype=int)
    probabilities = model.predict_proba(matrix)[:, list(model.named_steps["logit"].classes_).index(1)]
    two_classes = len(np.unique(labels)) == 2
    return {
        "labeled_count": int(len(rows)),
        "continuation_count": int(labels.sum()),
        "rebalance_count": int((labels == 0).sum()),
        "roc_auc": float(roc_auc_score(labels, probabilities)) if two_classes else None,
        "average_precision": float(average_precision_score(labels, probabilities)) if labels.sum() else None,
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "mean_probability_continuation": float(probabilities.mean()),
    }


def serialize_model(model: Pipeline, trained_rows: list[Opportunity]) -> dict[str, Any]:
    scaler: StandardScaler = model.named_steps["scale"]
    logit: LogisticRegression = model.named_steps["logit"]
    coefficients = logit.coef_[0]
    return {
        "model_id": MODEL_ID,
        "policy_id": POLICY_ID,
        "model_type": "shared_standardized_l2_logistic_competing_risk",
        "feature_names": list(FEATURE_NAMES),
        "hyperparameters": {
            "C": 0.25,
            "penalty": "l2",
            "solver": "lbfgs",
            "max_iter": 5000,
            "decision_bars": DECISION_BARS,
            "decision_cost_bps": DECISION_COST_BPS,
            "maximum_absolute_roll_residual_bps": MAX_ABS_ROLL_RESIDUAL_BPS,
            "minimum_gap_atr": MIN_GAP_ATR,
        },
        "training_labeled_count": len(labeled(trained_rows)),
        "scaler_mean": {name: float(value) for name, value in zip(FEATURE_NAMES, scaler.mean_)},
        "scaler_scale": {name: float(value) for name, value in zip(FEATURE_NAMES, scaler.scale_)},
        "coefficient": {name: float(value) for name, value in zip(FEATURE_NAMES, coefficients)},
        "intercept": float(logit.intercept_[0]),
    }


def route_opportunity(model: Pipeline, opportunity: Opportunity) -> RoutedSetup | None:
    probability = continuation_probability(model, opportunity)
    continuation_bps = abs(math.log(opportunity.continuation_level / opportunity.entry_price)) * 10_000.0
    rebalance_bps = abs(math.log(opportunity.rebalance_level / opportunity.entry_price)) * 10_000.0
    ev_continuation = (
        probability * continuation_bps
        - (1.0 - probability) * rebalance_bps
        - DECISION_COST_BPS
    )
    ev_rebalance = (
        (1.0 - probability) * rebalance_bps
        - probability * continuation_bps
        - DECISION_COST_BPS
    )
    selected_ev = max(ev_continuation, ev_rebalance)
    if not math.isfinite(selected_ev) or selected_ev <= 0:
        return None
    continuation_route = ev_continuation >= ev_rebalance
    if continuation_route:
        side = opportunity.direction
        target = opportunity.continuation_level
        stop = opportunity.rebalance_level
        route = "continuation"
    else:
        side = -opportunity.direction
        target = opportunity.rebalance_level
        stop = opportunity.continuation_level
        route = "rebalance"
    setup = core.Setup(
        config_id=POLICY_ID,
        family=f"cme_gap_ml_{route}",
        symbol=opportunity.symbol,
        gap_kind=opportunity.gap_kind,
        trading_date=opportunity.trading_date,
        side=side,
        event_open_ts=opportunity.event_open_ts,
        confirmation_end_ts=opportunity.entry_ts,
        entry_ts=opportunity.entry_ts,
        entry_price=opportunity.entry_price,
        stop_price=stop,
        target_price=target,
        score=selected_ev,
        gap_return_bps=0.0,
        roll_residual_bps=0.0,
    )
    return RoutedSetup(
        opportunity=opportunity,
        probability_continuation=probability,
        expected_value_continuation_bps=ev_continuation,
        expected_value_rebalance_bps=ev_rebalance,
        selected_expected_value_bps=selected_ev,
        selected_route=route,
        setup=setup,
    )


def simulate_stage(
    model: Pipeline,
    opportunities: list[Opportunity],
    bars_by_symbol: dict[str, pd.DataFrame],
    funding_by_symbol: dict[str, pd.Series],
) -> tuple[list[core.Trade], int, int, int, list[dict[str, Any]]]:
    routed = [item for opportunity in opportunities if (item := route_opportunity(model, opportunity)) is not None]
    routed.sort(key=lambda item: (item.setup.entry_ts, -item.selected_expected_value_bps, item.setup.symbol))
    trades: list[core.Trade] = []
    unresolved = 0
    skipped_global_slot = 0
    free_time = pd.Timestamp.min.tz_localize("UTC")
    decision_rows: list[dict[str, Any]] = []
    for item in routed:
        row = {
            "symbol": item.opportunity.symbol,
            "gap_kind": item.opportunity.gap_kind,
            "trading_date": item.opportunity.trading_date,
            "entry_ts": str(item.opportunity.entry_ts),
            "probability_continuation": item.probability_continuation,
            "ev_continuation_bps": item.expected_value_continuation_bps,
            "ev_rebalance_bps": item.expected_value_rebalance_bps,
            "selected_ev_bps": item.selected_expected_value_bps,
            "selected_route": item.selected_route,
            "slot_accepted": False,
            "resolved_trade": False,
        }
        if item.setup.entry_ts <= free_time:
            skipped_global_slot += 1
            decision_rows.append(row)
            continue
        row["slot_accepted"] = True
        trade = core.simulate_setup(
            item.setup,
            bars_by_symbol[item.setup.symbol],
            funding_by_symbol[item.setup.symbol],
        )
        if trade is None:
            unresolved += 1
            free_time = max(frame.index.max() for frame in bars_by_symbol.values())
            decision_rows.append(row)
            continue
        row["resolved_trade"] = True
        row["exit_ts"] = str(trade.exit_ts)
        row["gross_bps"] = trade.gross_bps
        trades.append(trade)
        free_time = trade.exit_ts
        decision_rows.append(row)
    return trades, unresolved, len(routed), skipped_global_slot, decision_rows


def compounded_return(values_bps: Iterable[float]) -> float:
    values = np.asarray(list(values_bps), dtype=float) / 10_000.0
    if not len(values):
        return 0.0
    if np.any(values <= -1.0):
        return -1.0
    return float(np.prod(1.0 + values) - 1.0)


def maximum_drawdown(values_bps: Iterable[float]) -> float:
    values = np.asarray(list(values_bps), dtype=float) / 10_000.0
    nav = [1.0]
    for value in values:
        nav.append(max(0.0, nav[-1] * (1.0 + value)))
    path = np.asarray(nav, dtype=float)
    peak = np.maximum.accumulate(path)
    return float(np.max(1.0 - path / np.maximum(peak, 1e-12)))


def top_removed_return(values_bps: np.ndarray, fraction: float = 0.10) -> float:
    if not len(values_bps):
        return 0.0
    positive_indices = np.flatnonzero(values_bps > 0)
    if not len(positive_indices):
        return compounded_return(values_bps)
    count = max(1, int(math.ceil(len(values_bps) * fraction)))
    order = positive_indices[np.argsort(values_bps[positive_indices])[::-1]]
    removed = set(order[:min(count, len(order))])
    retained = [value for index, value in enumerate(values_bps) if index not in removed]
    return compounded_return(retained)


def period_key(stage: str, timestamp: pd.Timestamp) -> str:
    if stage == "fit_holdout":
        return "P1" if timestamp.month <= 10 else "P2"
    return f"Q{(timestamp.month - 1) // 3 + 1}"


def required_periods(stage: str) -> tuple[str, ...]:
    return ("P1", "P2") if stage == "fit_holdout" else ("Q1", "Q2", "Q3", "Q4")


def stage_metrics(
    stage: str,
    trades: list[core.Trade],
    unresolved: int,
    eligible_opportunities: int,
    routed_count: int,
    skipped_global_slot: int,
    cost_bps: float,
) -> dict[str, Any]:
    net = np.asarray([trade.gross_bps - cost_bps for trade in trades], dtype=float)
    positive = net[net > 0]
    negative = net[net < 0]
    total = compounded_return(net)
    start, end = STAGE_BOUNDS[stage]
    days = int((end.normalize() - start.normalize()).days + 1)
    daily = -1.0 if total <= -1.0 else float(math.expm1(math.log1p(total) / days))
    period_indices = {key: [] for key in required_periods(stage)}
    for index, trade in enumerate(trades):
        period_indices[period_key(stage, trade.exit_ts)].append(index)
    period_returns = {
        key: compounded_return(net[indices]) if indices else 0.0
        for key, indices in period_indices.items()
    }
    positive_sum = float(positive.sum())
    symbol_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}
    for trade in trades:
        symbol_counts[trade.symbol] = symbol_counts.get(trade.symbol, 0) + 1
        route_counts[trade.family] = route_counts.get(trade.family, 0) + 1
    return {
        "eligible_opportunity_count": eligible_opportunities,
        "routed_positive_ev_count": routed_count,
        "skipped_global_slot_count": skipped_global_slot,
        "trade_count": int(len(trades)),
        "unresolved_positions": int(unresolved),
        "mean_trade_bps": float(net.mean()) if len(net) else None,
        "median_trade_bps": float(np.median(net)) if len(net) else None,
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) else None,
        "total_return": total,
        "geometric_daily_growth": daily,
        "maximum_drawdown": maximum_drawdown(net),
        "top_10_percent_positive_removed_return": top_removed_return(net),
        "top_five_positive_trade_share": (
            float(np.sort(positive)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0
        ),
        "positive_period_fraction": float(sum(value > 0 for value in period_returns.values()) / len(period_returns)),
        "period_returns": period_returns,
        "symbol_counts": symbol_counts,
        "route_counts": route_counts,
        "funding_bps_total": float(sum(trade.funding_bps for trade in trades)),
    }


def stage_gate(stage: str, metrics_by_cost: dict[str, dict[str, Any]]) -> bool:
    minimum_trades = 20 if stage == "fit_holdout" else 40
    base = metrics_by_cost["18"]
    return (
        base["trade_count"] >= minimum_trades
        and base["unresolved_positions"] == 0
        and base["mean_trade_bps"] is not None
        and base["mean_trade_bps"] > 0
        and metrics_by_cost["12"]["median_trade_bps"] is not None
        and metrics_by_cost["12"]["median_trade_bps"] > 0
        and metrics_by_cost["24"]["total_return"] > 0
        and base["top_10_percent_positive_removed_return"] > 0
        and base["top_five_positive_trade_share"] <= 0.50
        and base["positive_period_fraction"] >= (1.0 if stage == "fit_holdout" else 0.75)
    )


def serialize_trade(trade: core.Trade) -> dict[str, Any]:
    value = asdict(trade)
    value["entry_ts"] = str(trade.entry_ts)
    value["exit_ts"] = str(trade.exit_ts)
    return value


def opportunity_table(
    opportunities: list[Opportunity],
    model: Pipeline | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in opportunities:
        row = {
            "symbol": item.symbol,
            "gap_kind": item.gap_kind,
            "trading_date": item.trading_date,
            "event_open_ts": str(item.event_open_ts),
            "entry_ts": str(item.entry_ts),
            "direction": item.direction,
            "entry_price": item.entry_price,
            "rebalance_level": item.rebalance_level,
            "continuation_level": item.continuation_level,
            "continuation_label": item.continuation_label,
            "resolution": item.resolution,
            "resolution_ts": None if item.resolution_ts is None else str(item.resolution_ts),
        }
        row.update({name: value for name, value in zip(FEATURE_NAMES, item.feature_values)})
        if model is not None:
            row["probability_continuation"] = continuation_probability(model, item)
        rows.append(row)
    return pd.DataFrame(rows)


def evaluate_stage(
    stage: str,
    model: Pipeline,
    opportunities: list[Opportunity],
    bars_by_symbol: dict[str, pd.DataFrame],
    funding_by_symbol: dict[str, pd.Series],
) -> dict[str, Any]:
    start, end = STAGE_BOUNDS[stage]
    selected = [
        item for item in opportunities
        if start <= pd.Timestamp(item.entry_ts) <= end
    ]
    trades, unresolved, routed_count, skipped, decisions = simulate_stage(
        model, selected, bars_by_symbol, funding_by_symbol
    )
    metrics_by_cost = {
        str(cost): stage_metrics(
            stage,
            trades,
            unresolved,
            len(selected),
            routed_count,
            skipped,
            cost,
        )
        for cost in COSTS
    }
    return {
        "stage": stage,
        "stage_pass": stage_gate(stage, metrics_by_cost),
        "opportunity_count": len(selected),
        "labeled_opportunity_count": len(labeled(selected)),
        "model_diagnostics": model_diagnostics(model, selected),
        "metrics": metrics_by_cost,
        "trades": [serialize_trade(trade) for trade in trades],
        "decisions": decisions,
        "opportunities": selected,
    }


def run(output: Path, cache: Path) -> dict[str, Any]:
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    amendment = json.loads(AMENDMENT_PATH.read_text(encoding="utf-8"))
    if amendment["claim_id"] != prereg["claim_id"]:
        raise ValueError("ML amendment claim mismatch")
    if amendment["active_model_contract"]["policy_count"] != 1:
        raise ValueError("ML core must contain exactly one policy")
    output.mkdir(parents=True, exist_ok=True)

    all_source_records: list[dict[str, Any]] = []
    stage_outputs: dict[str, Any] = {}
    with core.requests.Session() as session:
        session.headers["User-Agent"] = "SMC-ICT-2-LIVE-CME-gap-ML/1.0"
        cme_2021, bars_2021, funding_2021, records_2021 = core.load_stage(session, cache, "fit")
        all_source_records.extend(records_2021)
        opportunities_2021 = build_opportunities(cme_2021, bars_2021)
        train_rows = [item for item in opportunities_2021 if item.entry_ts <= TRAIN_END]
        fit_rows = [item for item in opportunities_2021 if item.entry_ts >= FIT_HOLDOUT_START]
        model = fit_model(train_rows)
        fit_result = evaluate_stage("fit_holdout", model, fit_rows, bars_2021, funding_2021)
        stage_outputs["fit_holdout"] = fit_result
        opportunity_table(train_rows, model).to_csv(output / "train_2021_opportunities.csv", index=False)
        opportunity_table(fit_rows, model).to_csv(output / "fit_holdout_2021_opportunities.csv", index=False)
        write_json(output / "fit_model.json", serialize_model(model, train_rows))
        write_json(output / "fit_holdout_result.json", {key: value for key, value in fit_result.items() if key != "opportunities"})

        development_opened = bool(fit_result["stage_pass"])
        development_pass = False
        confirmation_opened = False
        confirmation_pass = False
        opportunities_2022: list[Opportunity] = []
        if development_opened:
            cme_2022, bars_2022, funding_2022, records_2022 = core.load_stage(session, cache, "development")
            all_source_records.extend(records_2022)
            opportunities_2022 = build_opportunities(cme_2022, bars_2022)
            development_result = evaluate_stage(
                "development", model, opportunities_2022, bars_2022, funding_2022
            )
            stage_outputs["development"] = development_result
            development_pass = bool(development_result["stage_pass"])
            opportunity_table(opportunities_2022, model).to_csv(output / "development_2022_opportunities.csv", index=False)
            write_json(output / "development_result.json", {key: value for key, value in development_result.items() if key != "opportunities"})

            confirmation_opened = development_pass
            if confirmation_opened:
                refit_rows = labeled(opportunities_2021 + opportunities_2022)
                refit_model = fit_model(refit_rows)
                write_json(output / "confirmation_model.json", serialize_model(refit_model, refit_rows))
                cme_2023, bars_2023, funding_2023, records_2023 = core.load_stage(session, cache, "confirmation")
                all_source_records.extend(records_2023)
                opportunities_2023 = build_opportunities(cme_2023, bars_2023)
                confirmation_result = evaluate_stage(
                    "confirmation", refit_model, opportunities_2023, bars_2023, funding_2023
                )
                stage_outputs["confirmation"] = confirmation_result
                confirmation_pass = bool(confirmation_result["stage_pass"])
                opportunity_table(opportunities_2023, refit_model).to_csv(output / "confirmation_2023_opportunities.csv", index=False)
                write_json(output / "confirmation_result.json", {key: value for key, value in confirmation_result.items() if key != "opportunities"})

    source_manifest = {
        "schema_version": 1,
        "claim_id": prereg["claim_id"],
        "scientific_contract": amendment["amendment_id"],
        "records": all_source_records,
        "stages_opened": {
            "fit_2021": True,
            "development_2022": development_opened,
            "confirmation_2023": confirmation_opened,
            "official_2024": False,
            "official_2025": False,
            "official_2026": False,
        },
        "orders_submitted": False,
    }
    write_json(output / "source_manifest.json", source_manifest)

    summary = {
        "schema_version": 1,
        "claim_id": prereg["claim_id"],
        "result_id": amendment["provisional_result_id"],
        "scientific_contract": amendment["amendment_id"],
        "model_id": MODEL_ID,
        "policy_count": 1,
        "model_type": "shared_standardized_l2_logistic_competing_risk",
        "trader_explanation": amendment["trader_explanation"],
        "fit_pass": bool(stage_outputs["fit_holdout"]["stage_pass"]),
        "development_opened": development_opened,
        "development_pass": development_pass,
        "confirmation_opened": confirmation_opened,
        "confirmation_pass": confirmation_pass,
        "stage_results": {
            key: {name: value for name, value in result.items() if name not in {"opportunities", "trades", "decisions"}}
            for key, result in stage_outputs.items()
        },
        "qualification": "FATAL_PROXY_ML_SCREEN_NOT_RANK_ELIGIBLE",
        "hard_validity_status": "PRELIMINARY_CAUSAL_ML_PROXY",
        "official_periods_opened": {"2024": False, "2025": False, "2026": False},
        "orders_submitted": False,
        "paper_or_testnet_started": False,
        "ranking_eligible": False,
        "legacy_432_rule_grid_executed": False,
    }
    write_json(output / "result_summary.json", summary)
    print("CME_GAP_ML_RESULT=" + json.dumps({
        "fit_pass": summary["fit_pass"],
        "development_opened": development_opened,
        "development_pass": development_pass,
        "confirmation_opened": confirmation_opened,
        "confirmation_pass": confirmation_pass,
    }, sort_keys=True), flush=True)
    return summary


def synthetic_bars() -> pd.DataFrame:
    index = pd.date_range("2021-01-01T00:00:00Z", periods=120, freq="15min")
    price = np.linspace(100.0, 101.0, len(index))
    frame = pd.DataFrame(index=index)
    frame["open"] = price
    frame["close"] = price + 0.02
    frame["high"] = np.maximum(frame["open"], frame["close"]) + 0.05
    frame["low"] = np.minimum(frame["open"], frame["close"]) - 0.05
    frame["quote_volume"] = 1000.0
    return frame


def self_test() -> None:
    bars = synthetic_bars()
    entry_ts = bars.index[100]
    continuation = 102.0
    rebalance = 99.0
    test = bars.copy()
    test.loc[entry_ts, "high"] = 102.1
    label, resolution, _ = first_touch_label(test, entry_ts, 1, continuation, rebalance)
    assert label == 1 and resolution == "continuation_first"
    test = bars.copy()
    test.loc[entry_ts, "low"] = 98.9
    label, resolution, _ = first_touch_label(test, entry_ts, 1, continuation, rebalance)
    assert label == 0 and resolution == "rebalance_first"
    test = bars.copy()
    test.loc[entry_ts, "high"] = 102.1
    test.loc[entry_ts, "low"] = 98.9
    label, resolution, _ = first_touch_label(test, entry_ts, 1, continuation, rebalance)
    assert label is None and resolution == "ambiguous_same_bar"

    rows: list[Opportunity] = []
    for number in range(80):
        values = tuple(float((number % (index + 3)) / (index + 3)) for index in range(len(FEATURE_NAMES)))
        rows.append(Opportunity(
            symbol="ETHUSDT" if number % 2 else "BTCUSDT",
            gap_kind="NWOG" if number % 5 == 0 else "NDOG",
            trading_date=f"2021-01-{number % 28 + 1:02d}",
            event_open_ts=entry_ts + pd.Timedelta(days=number),
            entry_ts=entry_ts + pd.Timedelta(days=number),
            direction=1 if number % 2 else -1,
            entry_price=100.0,
            rebalance_level=99.0 if number % 2 else 101.0,
            continuation_level=102.0 if number % 2 else 98.0,
            feature_values=values,
            continuation_label=number % 2,
            resolution="continuation_first" if number % 2 else "rebalance_first",
            resolution_ts=entry_ts + pd.Timedelta(days=number, hours=1),
        ))
    model = fit_model(rows)
    probabilities = [continuation_probability(model, row) for row in rows]
    assert all(0.0 <= value <= 1.0 for value in probabilities)
    serialized = serialize_model(model, rows)
    assert serialized["model_id"] == MODEL_ID
    assert len(serialized["coefficient"]) == len(FEATURE_NAMES)

    sample_net = np.asarray([50.0, -20.0, 30.0])
    assert compounded_return(sample_net - 12.0) >= compounded_return(sample_net - 18.0)
    assert compounded_return(sample_net - 18.0) >= compounded_return(sample_net - 24.0)
    assert POLICY_ID == hashlib.sha256(MODEL_ID.encode()).hexdigest()[:20]
    print("SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        run(args.output, args.cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
