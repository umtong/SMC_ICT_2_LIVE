#!/usr/bin/env python3
"""Freeze SMC action, exit and risk on 2023; evaluate untouched 2024H1.

Two causal order actions compete for the single global slot:
1. a passive mitigation order activated when the displacement PD array is known;
2. a marketable order activated only after post-mitigation rejection/CISD.

The existing candidate generator supplies the unified liquidity narrative. This file
changes neither that narrative nor official ranking. Its output is a coarse economic
screen requiring event-tape validation before ranking.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline

from run_research import PRIMARY, load_canonical_frames, load_instrument_rules
from system.core import EventCandidate, FeatureConfig
from system.model import candidate_model_features
from system.research_pipeline import generate_candidates_by_symbol


@dataclass(frozen=True)
class ActionLabel:
    activation: pd.Timestamp
    event_end: pd.Timestamp
    symbol: str
    action: str
    exit_variant: str
    filled: int
    entry_price: float
    loss_budget_per_unit: float
    net_pnl_per_unit: float
    features: dict[str, float]
    status: str


@dataclass(frozen=True)
class ScreenConfig:
    activation_latency_ms: int = 500
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.00055
    half_spread_bps: float = 0.25
    market_slippage_bps: float = 2.0
    stop_slippage_bps: float = 4.0
    maximum_leverage: float = 5.0
    risk_fraction: float = 0.01


def _jsonable(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return value


def _market_fill(base: float, order_side: int, config: ScreenConfig, *, stop: bool = False) -> float:
    slippage = config.stop_slippage_bps if stop else config.market_slippage_bps
    cost = (config.half_spread_bps + slippage) / 10000.0
    return float(base) * (1.0 + order_side * cost)


def _first(values: np.ndarray, start: int, level: float, upward: bool, end: int | None = None) -> int | None:
    view = values[start:end]
    positions = np.flatnonzero(view >= level if upward else view <= level)
    return start + int(positions[0]) if positions.size else None


def _prepare_bars(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy().sort_index()
    if "bar_start" not in out:
        out["bar_start"] = out.index
    out["bar_start"] = pd.to_datetime(out["bar_start"], utc=True)
    for name in ("open", "high", "low", "close"):
        out[name] = pd.to_numeric(out[name], errors="coerce")
    if "available_at" not in out.columns:
        out["available_at"] = out.index
    out["available_at"] = pd.to_datetime(out["available_at"], utc=True)
    return out.sort_values("bar_start", kind="stable").reset_index(drop=True)


def _funding_index(funding: Mapping[tuple[str, pd.Timestamp], float]) -> dict[str, list[tuple[pd.Timestamp, float]]]:
    result: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    for (symbol, timestamp), rate in funding.items():
        result.setdefault(symbol, []).append((pd.Timestamp(timestamp), float(rate)))
    for values in result.values():
        values.sort(key=lambda item: item[0])
    return result


def _funding_pnl_per_unit(symbol: str, side: int, entry: float, start: pd.Timestamp, end: pd.Timestamp,
                          funding: Mapping[str, list[tuple[pd.Timestamp, float]]]) -> float:
    total = 0.0
    for timestamp, rate in funding.get(symbol, []):
        if start < timestamp <= end:
            total -= side * entry * rate
    return total


def _candidate_features(candidate: EventCandidate, action: str, entry: float) -> dict[str, float]:
    values = candidate_model_features(candidate)
    if action == "EARLY_PASSIVE":
        blocked = ("retest", "mitigation", "entry_confirmation", "confirmation_age", "narrative_age")
        values = {name: value for name, value in values.items() if not any(token in name for token in blocked)}
    values["action_early_passive"] = float(action == "EARLY_PASSIVE")
    values["action_confirmed_market"] = float(action == "CONFIRMED_MARKET")
    values["action_entry_distance_from_confirmation_fraction"] = (
        (entry - candidate.entry_reference) / max(candidate.entry_reference, 1e-12)
    )
    values["action_stop_distance_fraction"] = abs(entry - candidate.stop_reference) / max(entry, 1e-12)
    values["action_target_distance_fraction"] = abs(candidate.target_reference - entry) / max(entry, 1e-12)
    values["action_raw_reward_risk"] = abs(candidate.target_reference - entry) / max(abs(entry - candidate.stop_reference), 1e-12)
    return {str(k): float(v) for k, v in values.items() if np.isfinite(float(v))}


def _early_geometry(candidate: EventCandidate) -> tuple[pd.Timestamp, float] | None:
    features = candidate.feature_row
    distance = features.get("zone_midpoint_distance_atr", features.get("retest_midpoint_distance_atr"))
    age = features.get("confirmation_age_bars", features.get("retest_wait_bars"))
    if distance is None or age is None:
        return None
    atr = features.get("atr")
    if atr is None:
        atr_fraction = features.get("atr_fraction")
        if atr_fraction is None:
            stop_atr = features.get("stop_distance_atr")
            if stop_atr is None or float(stop_atr) <= 0:
                return None
            atr = abs(candidate.entry_reference - candidate.stop_reference) / float(stop_atr)
        else:
            atr = candidate.entry_reference * float(atr_fraction)
    if not np.isfinite(float(atr)) or float(atr) <= 0:
        return None
    entry = candidate.entry_reference - float(distance) * float(atr)
    bars = max(1, int(round(float(age))))
    activation = candidate.timestamp - pd.Timedelta(minutes=5 * bars)
    return activation, float(entry)


def _label_action(candidate: EventCandidate, action: str, exit_variant: str, bars: pd.DataFrame,
                  funding: Mapping[str, list[tuple[pd.Timestamp, float]]], evaluation_end: pd.Timestamp,
                  config: ScreenConfig) -> ActionLabel | None:
    side = int(candidate.side)
    data = _prepare_bars(bars)
    starts = pd.DatetimeIndex(data["bar_start"]).as_unit("ns").asi8
    high = data["high"].to_numpy(float)
    low = data["low"].to_numpy(float)
    opens = data["open"].to_numpy(float)
    available = pd.DatetimeIndex(pd.to_datetime(data["available_at"], utc=True))
    evaluation_limit = int(np.searchsorted(starts, evaluation_end.value, side="left"))

    if action == "EARLY_PASSIVE":
        geometry = _early_geometry(candidate)
        if geometry is None:
            return None
        signal_time, entry_reference = geometry
        activation = signal_time + pd.Timedelta(milliseconds=config.activation_latency_ms)
    else:
        entry_reference = float(candidate.entry_reference)
        activation = candidate.timestamp + pd.Timedelta(milliseconds=config.activation_latency_ms)

    start = int(np.searchsorted(starts, activation.value, side="left"))
    if start >= evaluation_limit:
        return None
    stop = float(candidate.stop_reference)
    target = float(candidate.target_reference)
    if not (side * (entry_reference - stop) > 0 and side * (target - entry_reference) > 0):
        return None

    if action == "EARLY_PASSIVE":
        if side > 0:
            invalidation = _first(low, start, stop, False, evaluation_limit)
            target_before_fill = _first(high, start, target, True, evaluation_limit)
            fill = _first(low, start, float(np.nextafter(entry_reference, -np.inf)), False, evaluation_limit)
        else:
            invalidation = _first(high, start, stop, True, evaluation_limit)
            target_before_fill = _first(low, start, target, False, evaluation_limit)
            fill = _first(high, start, float(np.nextafter(entry_reference, np.inf)), True, evaluation_limit)
        first_boundary = min([value for value in (invalidation, target_before_fill) if value is not None], default=None)
        if fill is None or (first_boundary is not None and first_boundary <= fill):
            end_position = first_boundary if first_boundary is not None else evaluation_limit - 1
            return ActionLabel(
                activation, available[end_position], candidate.symbol, action, exit_variant, 0,
                entry_reference, max(abs(entry_reference - stop), 1e-12), 0.0,
                _candidate_features(candidate, action, entry_reference), "CANCELLED_OR_UNFILLED",
            )
        entry_position = fill
        entry_price = entry_reference
        entry_fee = config.maker_fee_rate
    else:
        entry_position = start
        entry_price = _market_fill(opens[entry_position], side, config)
        entry_fee = config.taker_fee_rate
        if not (side * (entry_price - stop) > 0 and side * (target - entry_price) > 0):
            return ActionLabel(
                activation, available[entry_position], candidate.symbol, action, exit_variant, 0,
                entry_price, max(abs(entry_price - stop), 1e-12), 0.0,
                _candidate_features(candidate, action, entry_price), "CANCELLED_INVALID_GEOMETRY",
            )

    estimated_stop = stop * (1.0 - side * (config.half_spread_bps + config.stop_slippage_bps) / 10000.0)
    loss_budget = abs(entry_price - estimated_stop) + entry_price * entry_fee + estimated_stop * config.taker_fee_rate
    risk_distance = abs(entry_price - stop)
    cap_target = target if abs(target - entry_price) <= 2.0 * risk_distance else entry_price + side * 2.0 * risk_distance
    effective_target = target if exit_variant == "FULL_STRUCTURAL" else cap_target

    if side > 0:
        stop_position = _first(low, entry_position, stop, False, evaluation_limit)
        target_position = _first(high, entry_position, effective_target, True, evaluation_limit)
    else:
        stop_position = _first(high, entry_position, stop, True, evaluation_limit)
        target_position = _first(low, entry_position, effective_target, False, evaluation_limit)

    if stop_position is not None and (target_position is None or stop_position <= target_position):
        position = stop_position
        base = min(opens[position], stop) if side > 0 else max(opens[position], stop)
        exit_price = _market_fill(base, -side, config, stop=True)
        status = "STOP"
    elif target_position is not None:
        position = target_position
        exit_price = _market_fill(effective_target, -side, config)
        status = "STRUCTURAL_TARGET" if effective_target == target else "CAP_2R"
    else:
        position = max(entry_position, evaluation_limit - 1)
        close = float(data["close"].iloc[position])
        exit_price = _market_fill(close, -side, config)
        status = "EVALUATION_MARK"

    end = available[position]
    pnl = side * (exit_price - entry_price) - entry_price * entry_fee - exit_price * config.taker_fee_rate
    pnl += _funding_pnl_per_unit(candidate.symbol, side, entry_price, available[entry_position], end, funding)
    return ActionLabel(
        activation, end, candidate.symbol, action, exit_variant, 1, entry_price,
        max(loss_budget, 1e-12), pnl, _candidate_features(candidate, action, entry_price), status,
    )


def _rows(candidates: Sequence[EventCandidate], execution: Mapping[str, pd.DataFrame],
          funding: Mapping[tuple[str, pd.Timestamp], float], evaluation_end: pd.Timestamp,
          variants: Sequence[str], config: ScreenConfig) -> pd.DataFrame:
    indexed_funding = _funding_index(funding)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        frame = execution.get(candidate.symbol)
        if frame is None:
            continue
        for action in ("EARLY_PASSIVE", "CONFIRMED_MARKET"):
            for variant in variants:
                label = _label_action(candidate, action, variant, frame, indexed_funding, evaluation_end, config)
                if label is None:
                    continue
                row = {
                    "activation": label.activation,
                    "event_end": label.event_end,
                    "symbol": label.symbol,
                    "action": label.action,
                    "exit_variant": label.exit_variant,
                    "filled": label.filled,
                    "entry_price": label.entry_price,
                    "loss_budget_per_unit": label.loss_budget_per_unit,
                    "net_pnl_per_unit": label.net_pnl_per_unit,
                    "net_budget_r": label.net_pnl_per_unit / max(label.loss_budget_per_unit, 1e-12),
                    "status": label.status,
                }
                row.update(label.features)
                rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["activation", "symbol", "action", "exit_variant"], kind="stable").reset_index(drop=True)


def _feature_columns(rows: pd.DataFrame) -> list[str]:
    excluded = {
        "activation", "event_end", "symbol", "action", "exit_variant", "filled",
        "entry_price", "loss_budget_per_unit", "net_pnl_per_unit", "net_budget_r", "status",
    }
    return [name for name in rows.columns if name not in excluded and pd.api.types.is_numeric_dtype(rows[name])]


def _fit(rows: pd.DataFrame, features: Sequence[str]):
    model = make_pipeline(
        SimpleImputer(strategy="median"),
        HistGradientBoostingRegressor(
            learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=30,
            max_iter=250, l2_regularization=2.0, random_state=20260727,
        ),
    )
    model.fit(rows[list(features)], rows["net_budget_r"].astype(float))
    return model


def _account(rows: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, threshold: float,
             risk_fraction: float, maximum_leverage: float,
             instrument_rules: Mapping[str, tuple[float, float]]) -> dict[str, Any]:
    eligible = rows[(rows["activation"] >= start) & (rows["activation"] < end) & (rows["score"] >= threshold)].copy()
    eligible = eligible.sort_values(["activation", "score", "symbol"], ascending=[True, False, True], kind="stable")
    nav = 10000.0
    peak = nav
    maximum_drawdown = 0.0
    occupied_until = start
    records: list[dict[str, Any]] = []
    returns: list[float] = []
    for timestamp, group in eligible.groupby("activation", sort=True):
        if timestamp < occupied_until:
            continue
        row = group.iloc[0]
        end_time = max(timestamp, pd.Timestamp(row["event_end"]))
        occupied_until = end_time
        if int(row["filled"]) == 0:
            records.append({"activation": timestamp, "event_end": end_time, "symbol": row["symbol"], "action": row["action"], "filled": 0, "return": 0.0})
            continue
        step, minimum = instrument_rules[str(row["symbol"])]
        planned = nav * risk_fraction / max(float(row["loss_budget_per_unit"]), 1e-12)
        leverage_cap = nav * maximum_leverage / max(float(row["entry_price"]), 1e-12)
        quantity = min(planned, leverage_cap)
        quantity = np.floor(quantity / step) * step
        if quantity < minimum:
            continue
        pnl = quantity * float(row["net_pnl_per_unit"])
        trade_return = pnl / nav
        if trade_return <= -1.0:
            nav = 0.0
            returns.append(-1.0)
            records.append({"activation": timestamp, "event_end": end_time, "symbol": row["symbol"], "action": row["action"], "filled": 1, "return": -1.0})
            break
        nav += pnl
        returns.append(trade_return)
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, 1.0 - nav / peak)
        records.append({"activation": timestamp, "event_end": end_time, "symbol": row["symbol"], "action": row["action"], "filled": 1, "return": trade_return, "nav": nav, "score": float(row["score"])})
    days = max(1, (end - start).days)
    geometric = -1.0 if nav <= 0 else float(np.exp(np.log(nav / 10000.0) / days) - 1.0)
    return {
        "ending_nav": nav,
        "nav_multiple": nav / 10000.0,
        "geometric_daily_growth": geometric,
        "maximum_drawdown_at_realized_events": maximum_drawdown,
        "filled_trades": sum(int(item.get("filled", 0)) for item in records),
        "decisions": len(records),
        "records": records,
    }


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    rules = load_instrument_rules(args.instrument_rules, PRIMARY)
    rule_map = {row.symbol: (row.quantity_step, row.minimum_quantity) for row in rules}
    screen = ScreenConfig()
    variants = ("FULL_STRUCTURAL", "CAP_2R", "TP1_50_BE_STRUCT")

    decision_2023, execution_2023, funding_2023 = load_canonical_frames(
        args.data_root, args.repo_root, PRIMARY, ("PRE_2024_2023",)
    )
    _, candidates_2023 = generate_candidates_by_symbol(decision_2023, FeatureConfig())
    rows_2023 = _rows(candidates_2023, execution_2023, funding_2023, pd.Timestamp("2024-01-01T00:00:00Z"), variants, screen)
    rows_2023.to_parquet(args.output / "ACTION_LABELS_2023.parquet", index=False)
    if rows_2023.empty:
        raise RuntimeError("no causal action rows in 2023")

    h1_start = pd.Timestamp("2023-01-01T00:00:00Z")
    h2_start = pd.Timestamp("2023-07-01T00:00:00Z")
    pre_end = pd.Timestamp("2024-01-01T00:00:00Z")
    training = rows_2023[(rows_2023["activation"] >= h1_start) & (rows_2023["activation"] < h2_start) & (rows_2023["event_end"] < h2_start)].copy()
    validation = rows_2023[(rows_2023["activation"] >= h2_start) & (rows_2023["activation"] < pre_end)].copy()
    features = _feature_columns(rows_2023)

    selections: list[dict[str, Any]] = []
    for variant in variants:
        train_variant = training[training["exit_variant"] == variant].copy()
        validation_variant = validation[validation["exit_variant"] == variant].copy()
        if len(train_variant) < 100 or len(validation_variant) < 50:
            continue
        model = _fit(train_variant, features)
        validation_variant["score"] = model.predict(validation_variant[features])
        for quantile in (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.925, 0.95):
            threshold = float(validation_variant["score"].quantile(quantile))
            base = _account(validation_variant, h2_start, pre_end, threshold, 0.01, 5.0, rule_map)
            if base["filled_trades"] < 15 or base["geometric_daily_growth"] <= 0:
                continue
            best_risk = None
            for risk_fraction in (0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.20):
                for leverage in (5.0, 10.0, 20.0, 50.0, 100.0):
                    account = _account(validation_variant, h2_start, pre_end, threshold, risk_fraction, leverage, rule_map)
                    if account["ending_nav"] <= 0:
                        continue
                    key = (account["geometric_daily_growth"], account["nav_multiple"], -account["maximum_drawdown_at_realized_events"])
                    if best_risk is None or key > best_risk[0]:
                        best_risk = (key, risk_fraction, leverage, account)
            selections.append({
                "variant": variant, "quantile": quantile, "threshold_h2": threshold,
                "base_account_h2": base,
                "risk_fraction": best_risk[1], "maximum_leverage": best_risk[2],
                "optimized_account_h2": best_risk[3],
            })
    if not selections:
        summary = {
            "schema_version": 1, "stage": "PRE2024_CAUSAL_ACTION_COARSE_NOT_RANKABLE",
            "decision": "NO_POSITIVE_CAUSAL_ACTION_SURVIVOR",
            "candidate_count_2023": len(candidates_2023), "action_rows_2023": len(rows_2023),
            "ranking_effect": "NONE",
        }
        (args.output / "CAUSAL_ACTION_RESULT.json").write_text(json.dumps(summary, indent=2) + "\n")
        return 0

    selected = max(
        selections,
        key=lambda row: (
            row["optimized_account_h2"]["geometric_daily_growth"],
            row["optimized_account_h2"]["nav_multiple"],
            -row["optimized_account_h2"]["maximum_drawdown_at_realized_events"],
        ),
    )
    all_pre = rows_2023[(rows_2023["activation"] < pre_end) & (rows_2023["event_end"] < pre_end) & (rows_2023["exit_variant"] == selected["variant"])].copy()
    model = _fit(all_pre, features)
    all_pre["score"] = model.predict(all_pre[features])
    frozen_threshold = float(all_pre["score"].quantile(selected["quantile"]))

    decision_2024, execution_2024, funding_2024 = load_canonical_frames(
        args.data_root, args.repo_root, PRIMARY, ("2024_H1",)
    )
    _, candidates_2024 = generate_candidates_by_symbol(decision_2024, FeatureConfig())
    rows_2024 = _rows(
        candidates_2024, execution_2024, funding_2024,
        pd.Timestamp("2024-07-01T00:00:00Z"), (selected["variant"],), screen,
    )
    rows_2024["score"] = model.predict(rows_2024[features])
    result_2024 = _account(
        rows_2024, pd.Timestamp("2024-01-01T00:00:00Z"), pd.Timestamp("2024-07-01T00:00:00Z"),
        frozen_threshold, float(selected["risk_fraction"]), float(selected["maximum_leverage"]), rule_map,
    )
    rows_2024.to_parquet(args.output / "ACTION_LABELS_2024_H1.parquet", index=False)

    summary = {
        "schema_version": 1,
        "stage": "2024_H1_CAUSAL_ACTION_COARSE_NOT_RANKABLE",
        "selection_information_cutoff": "2023-12-31T23:59:59.999999Z",
        "fixed_activation_latency_ms": screen.activation_latency_ms,
        "candidate_count_2023": len(candidates_2023),
        "action_rows_2023": len(rows_2023),
        "candidate_count_2024_h1": len(candidates_2024),
        "action_rows_2024_h1": len(rows_2024),
        "selected_pre2024": selected,
        "frozen_threshold": frozen_threshold,
        "feature_count": len(features),
        "result_2024_h1": result_2024,
        "decision": (
            "ADVANCE_EXACT_CAUSAL_ACTION_SURVIVOR_TO_EVENT_TAPE_AND_CONTINUOUS_EVALUATION"
            if result_2024["geometric_daily_growth"] > 0
            else "KEEP_UNIFIED_SMC_NARRATIVE_REPAIR_ACTION_VALUE_OR_ENTRY_GEOMETRY"
        ),
        "target_exceeded_coarse": result_2024["geometric_daily_growth"] >= 0.01,
        "ranking_effect": "NONE_COARSE_1M_NOT_RANKABLE",
    }
    path = args.output / "CAUSAL_ACTION_RESULT.json"
    path.write_text(json.dumps(_jsonable(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    (args.output / "CAUSAL_ACTION_RESULT.sha256").write_text(f"{sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    print(json.dumps(_jsonable(summary), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--instrument-rules", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
