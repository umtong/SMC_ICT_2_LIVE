#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import brier_score_loss, mean_absolute_error, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
DEVELOPMENT_START = pd.Timestamp("2022-04-03T00:00:00Z")
DEVELOPMENT_END = pd.Timestamp("2023-01-01T00:00:00Z")
CONFIRMATION_END = pd.Timestamp("2024-01-01T00:00:00Z")
VALIDATION_SPLIT = pd.Timestamp("2022-09-01T00:00:00Z")
COST_NAMES = ("15bp", "18bp", "24bp")


def import_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def candidate(original):
    return original.Candidate(
        family="aligned_continuation", horizon_bars=48, z_min=3.0, z_max=math.inf,
        terminal_bars=3, flow_threshold=0.10, efficiency_min=0.45, hold_min=0.70,
        stop_buffer_atr=0.50, reward_risk=4.0, maximum_holding_minutes=720,
        cross_state="idiosyncratic",
    )


def build_feature_table(events, features: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for event in events:
        frame = features[event.symbol]
        if event.signal_open_time not in frame.index:
            continue
        row = frame.loc[event.signal_open_time]
        side = int(event.side)
        hold = float(row.long_hold_48 if side > 0 else row.short_hold_48)
        timestamp = event.decision_time
        rows.append({
            "event_key": f"{event.symbol}|{event.decision_time.isoformat()}|{event.side}",
            "decision_time": timestamp,
            "year": int(timestamp.year),
            "symbol": event.symbol,
            "side": side,
            "score": float(event.score),
            "abs_z": abs(float(row.z_48)),
            "directional_displacement": side * float(row.disp_48),
            "efficiency": float(row.eff_48),
            "directional_flow": side * float(row.flow_3),
            "directional_hold": hold,
            "directional_common": side * float(row.common_48),
            "directional_residual": side * float(row.residual_48),
            "volume_z": float(row.volume_z),
            "trade_z": float(row.trade_z),
            "atr_fraction": float(row.atr / row.close),
            "stop_distance_atr": float(abs(float(row.close) - event.stop_reference) / row.atr),
            "hour_sin": math.sin(2 * math.pi * timestamp.hour / 24),
            "hour_cos": math.cos(2 * math.pi * timestamp.hour / 24),
            "dow_sin": math.sin(2 * math.pi * timestamp.dayofweek / 7),
            "dow_cos": math.cos(2 * math.pi * timestamp.dayofweek / 7),
            **{f"symbol_{symbol}": float(event.symbol == symbol) for symbol in SYMBOLS},
        })
    table = pd.DataFrame(rows).sort_values(["decision_time", "event_key"]).reset_index(drop=True)
    table["decision_time"] = pd.to_datetime(table.decision_time, utc=True)
    return table


def add_counterfactuals(table: pd.DataFrame, event_map, candidate_value, minute, funding,
                        costs, engine, fifteen, promotions, audit) -> pd.DataFrame:
    output = table.copy()
    for cost_name in COST_NAMES:
        cost = costs[cost_name]
        values = []
        holding = []
        reasons = []
        for event_key in output.event_key:
            trade = audit.execute(
                event_map[event_key], candidate_value, 10_000.0, minute, funding,
                cost, engine, "protected_flow", fifteen, promotions,
            )
            values.append(float(trade.r_multiple) if trade is not None else 0.0)
            holding.append(int(trade.holding_minutes) if trade is not None else 0)
            reasons.append(trade.exit_reason if trade is not None else "invalid")
        output[f"r_{cost_name}"] = values
        output[f"holding_{cost_name}"] = holding
        output[f"reason_{cost_name}"] = reasons
    output["robust_utility"] = (
        output["r_18bp"].clip(-1.25, 2.0) + output["r_24bp"].clip(-1.25, 2.0)
    ) / 2.0
    output["positive_18bp"] = (output.r_18bp > 0).astype(int)
    return output


def feature_columns(table: pd.DataFrame) -> list[str]:
    excluded = {
        "event_key", "decision_time", "year", "symbol",
        "r_15bp", "r_18bp", "r_24bp", "holding_15bp", "holding_18bp", "holding_24bp",
        "reason_15bp", "reason_18bp", "reason_24bp", "robust_utility", "positive_18bp",
    }
    return [column for column in table.columns if column not in excluded]


def proper_simulate(events, candidate_value, minute, funding, cost, engine, fifteen, promotions, audit,
                    start: pd.Timestamp, end: pd.Timestamp,
                    score_by_key: dict[str, float] | None = None,
                    allowed_symbols: set[str] | None = None,
                    banned_event_keys: set[str] | None = None):
    allowed_symbols = allowed_symbols or set(SYMBOLS)
    banned_event_keys = banned_event_keys or set()
    filtered = [event for event in events if start <= event.entry_time < end]
    nav = engine.initial_nav
    free_time = start
    trades = []
    index = 0
    while index < len(filtered):
        timestamp = filtered[index].entry_time
        group = []
        while index < len(filtered) and filtered[index].entry_time == timestamp:
            event = filtered[index]
            index += 1
            key = f"{event.symbol}|{event.decision_time.isoformat()}|{event.side}"
            if event.symbol not in allowed_symbols or key in banned_event_keys:
                continue
            policy_score = event.score if score_by_key is None else score_by_key.get(key, float("-inf"))
            if not np.isfinite(policy_score) or (score_by_key is not None and policy_score <= 0):
                continue
            group.append((policy_score, event))
        if timestamp < free_time or not group:
            continue
        _, selected = max(group, key=lambda pair: (pair[0], pair[1].score, -SYMBOLS.index(pair[1].symbol)))
        trade = audit.execute(
            selected, candidate_value, nav, minute, funding, cost, engine,
            "protected_flow", fifteen, promotions,
        )
        if trade is None:
            continue
        nav += trade.net_pnl
        trades.append(trade)
        if nav <= 0:
            break
        free_time = trade.exit_time + pd.Timedelta(minutes=1)
    frame = pd.DataFrame([dataclasses.asdict(trade) for trade in trades])
    daily_index = pd.date_range(start.floor("D"), end, freq="1D", inclusive="left", tz="UTC")
    daily = pd.Series(engine.initial_nav, index=daily_index, dtype=float)
    if not frame.empty:
        frame["exit_time"] = pd.to_datetime(frame.exit_time, utc=True)
        cumulative = engine.initial_nav + frame.set_index("exit_time").net_pnl.cumsum()
        union = daily.index.union(cumulative.index).sort_values()
        daily = cumulative.reindex(union).ffill().fillna(engine.initial_nav).reindex(daily.index, method="ffill").fillna(engine.initial_nav)
    return frame, daily


def path_metrics(trades: pd.DataFrame, daily: pd.Series, start: pd.Timestamp, end: pd.Timestamp,
                 initial_nav: float = 10_000.0) -> dict[str, Any]:
    if trades.empty:
        return {
            "trade_count": 0, "final_nav": initial_nav, "total_return": 0.0,
            "geometric_daily": 0.0, "profit_factor": 0.0, "maximum_drawdown": 0.0,
            "mean_r": None, "median_r": None, "top5_positive_share": 1.0,
            "positive_month_fraction": 0.0, "median_holding_minutes": None,
            "exit_reasons": {}, "symbol_counts": {},
        }
    final_nav = initial_nav + float(trades.net_pnl.sum())
    days = float((end - start) / pd.Timedelta(days=1))
    geometric = (final_nav / initial_nav) ** (1 / days) - 1 if final_nav > 0 else -1.0
    curve = daily.to_numpy(float)
    mdd = float(np.max(1 - curve / np.maximum.accumulate(curve)))
    positive = trades.loc[trades.net_pnl > 0, "net_pnl"]
    negative = -trades.loc[trades.net_pnl < 0, "net_pnl"]
    pf = float(positive.sum() / negative.sum()) if negative.sum() > 0 else (999.0 if positive.sum() > 0 else 0.0)
    top5 = float(positive.nlargest(5).sum() / positive.sum()) if positive.sum() > 0 else 1.0
    monthly = trades.set_index("exit_time").net_pnl.resample("MS").sum()
    return {
        "trade_count": int(len(trades)), "final_nav": final_nav,
        "total_return": final_nav / initial_nav - 1, "geometric_daily": float(geometric),
        "profit_factor": pf, "maximum_drawdown": mdd,
        "mean_r": float(trades.r_multiple.mean()), "median_r": float(trades.r_multiple.median()),
        "top5_positive_share": top5,
        "positive_month_fraction": float((monthly > 0).mean()) if len(monthly) else 0.0,
        "median_holding_minutes": float(trades.holding_minutes.median()),
        "exit_reasons": {str(k): int(v) for k, v in trades.exit_reason.value_counts().items()},
        "symbol_counts": {str(k): int(v) for k, v in trades.symbol.value_counts().items()},
    }


def exact_winner_reroute(events, candidate_value, minute, funding, cost, engine, fifteen, promotions,
                         audit, start, end, trades, score_by_key=None, allowed_symbols=None):
    if trades.empty:
        return set(), trades, pd.Series(engine.initial_nav, index=pd.date_range(start, end, freq="1D", inclusive="left", tz="UTC"))
    count = min(max(1, math.ceil(len(trades) * 0.10)), len(trades))
    removed = set(trades.nlargest(count, "net_pnl").event_key)
    rerouted, daily = proper_simulate(
        events, candidate_value, minute, funding, cost, engine, fifteen, promotions, audit,
        start, end, score_by_key=score_by_key, allowed_symbols=allowed_symbols,
        banned_event_keys=removed,
    )
    return removed, rerouted, daily


def evaluate_policy(name, events, candidate_value, minute, funding, costs, engine, fifteen, promotions,
                    audit, start, end, score_by_key=None, allowed_symbols=None):
    rows = []
    ledgers = []
    for cost_name in COST_NAMES:
        cost = costs[cost_name]
        trades, daily = proper_simulate(
            events, candidate_value, minute, funding, cost, engine, fifteen, promotions, audit,
            start, end, score_by_key=score_by_key, allowed_symbols=allowed_symbols,
        )
        base = path_metrics(trades, daily, start, end)
        removed, rerouted, rerouted_daily = exact_winner_reroute(
            events, candidate_value, minute, funding, cost, engine, fifteen, promotions,
            audit, start, end, trades, score_by_key=score_by_key, allowed_symbols=allowed_symbols,
        )
        row = {
            "policy": name, "cost": cost_name, "period_start": start.isoformat(), "period_end": end.isoformat(),
            **base,
            "winner_reroute": {"removed_count": len(removed), **path_metrics(rerouted, rerouted_daily, start, end)},
        }
        rows.append(row)
        if not trades.empty:
            copy = trades.copy(); copy["policy"] = name; copy["cost"] = cost_name
            copy["period_start"] = start; copy["period_end"] = end
            ledgers.append(copy)
    return rows, ledgers


def spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(pd.Series(y_true).corr(pd.Series(y_pred), method="spearman")) if len(y_true) > 1 else float("nan")


def fit_models(train: pd.DataFrame, columns: list[str]):
    x = train[columns].to_numpy(float)
    y = train.robust_utility.to_numpy(float)
    positive = train.positive_18bp.to_numpy(int)
    models = {
        "ridge_robust_value": make_pipeline(StandardScaler(), Ridge(alpha=10.0)),
        "hgbt_robust_value": HistGradientBoostingRegressor(
            loss="squared_error", learning_rate=0.05, max_iter=120, max_depth=2,
            min_samples_leaf=20, l2_regularization=5.0, random_state=17,
        ),
        "hgbt_positive_probability": HistGradientBoostingClassifier(
            loss="log_loss", learning_rate=0.05, max_iter=120, max_depth=2,
            min_samples_leaf=20, l2_regularization=5.0, random_state=17,
        ),
    }
    models["ridge_robust_value"].fit(x, y)
    models["hgbt_robust_value"].fit(x, y)
    models["hgbt_positive_probability"].fit(x, positive)
    return models


def model_scores(model_name: str, model, table: pd.DataFrame, columns: list[str]) -> np.ndarray:
    x = table[columns].to_numpy(float)
    if model_name.endswith("positive_probability"):
        probability = model.predict_proba(x)[:, 1]
        # Fixed expected-utility transform using only the training payoff ratio.
        return probability - 0.5
    return model.predict(x)


def model_diagnostics(model_name: str, model, table: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    x = table[columns].to_numpy(float)
    y = table.robust_utility.to_numpy(float)
    constant = np.full(len(table), y.mean() if len(table) else 0.0)
    if model_name.endswith("positive_probability"):
        actual = table.positive_18bp.to_numpy(int)
        probability = model.predict_proba(x)[:, 1]
        baseline = np.full(len(table), actual.mean() if len(actual) else 0.0)
        return {
            "rows": len(table),
            "auc": float(roc_auc_score(actual, probability)) if len(np.unique(actual)) == 2 else None,
            "brier": float(brier_score_loss(actual, probability)),
            "constant_brier": float(brier_score_loss(actual, baseline)),
            "spearman_utility": spearman(y, probability),
        }
    prediction = model.predict(x)
    return {
        "rows": len(table), "mae": float(mean_absolute_error(y, prediction)),
        "constant_mae": float(mean_absolute_error(y, constant)),
        "spearman": spearman(y, prediction),
    }


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# Aligned-continuation causal policy refinement",
        "",
        f"Decision: `{result['decision']['status']}`",
        f"Development-selected symbols: `{','.join(result['development_symbol_rule']['allowed_symbols'])}`",
        "",
        "## Account paths",
        "",
        "| policy | period | cost | trades | return | PF | MDD | top-5 share | correct winner reroute | symbols |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in result["paths"]:
        period = "2022" if row["period_end"].startswith("2023-01-01") else ("2023" if row["period_start"].startswith("2023-01-01") else "2022-forward")
        lines.append(
            f"| {row['policy']} | {period} | {row['cost']} | {row['trade_count']} | {row['total_return']:.4%} | "
            f"{row['profit_factor']:.3f} | {row['maximum_drawdown']:.3%} | {row['top5_positive_share']:.2%} | "
            f"{row['winner_reroute']['total_return']:.4%} | `{json.dumps(row['symbol_counts'], sort_keys=True)}` |"
        )
    lines += ["", "## Model diagnostics", "", "```json", json.dumps(result["model_diagnostics"], indent=2), "```", ""]
    lines += [
        "Winner deletion now removes the selected event and reroutes the same timestamp to the next eligible candidate. "
        "It is a concentration diagnostic, not a standalone eligibility objective.",
        "",
        "No credentials or orders were used.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-source", type=Path, required=True)
    parser.add_argument("--audit-source", type=Path, required=True)
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    original = import_path("registered_absorption_flow_policy", args.original_source)
    audit = import_path("aligned_current_contract", args.audit_source)
    minute = {symbol: original.load_minute(args.prepared_root / f"{symbol}_minute.parquet") for symbol in SYMBOLS}
    funding = {symbol: original.load_funding(args.prepared_root / f"{symbol}_funding.parquet") for symbol in SYMBOLS}
    five = {symbol: original.strict_resample_5m(frame) for symbol, frame in minute.items()}
    features = original.prepare_features(five)
    candidate_value = candidate(original)
    events = original.generate_events(features, candidate_value, DEVELOPMENT_START, CONFIRMATION_END)
    event_map = {f"{event.symbol}|{event.decision_time.isoformat()}|{event.side}": event for event in events}
    fifteen = {symbol: audit.strict_15m(frame) for symbol, frame in minute.items()}
    promotions = {symbol: audit.protected_promotions(fifteen[symbol]) for symbol in SYMBOLS}
    costs = {cost.name: cost for cost in audit.COSTS}
    engine = audit.Engine()

    table = build_feature_table(events, features)
    table = add_counterfactuals(table, event_map, candidate_value, minute, funding, costs, engine, fifteen, promotions, audit)
    table.to_parquet(args.output / "EVENT_ACTION_VALUE.parquet", index=False)
    columns = feature_columns(table)

    development = table[(table.decision_time >= DEVELOPMENT_START) & (table.decision_time < DEVELOPMENT_END)]
    early = development[development.decision_time < VALIDATION_SPLIT]
    late = development[development.decision_time >= VALIDATION_SPLIT]
    confirmation = table[(table.decision_time >= DEVELOPMENT_END) & (table.decision_time < CONFIRMATION_END)]

    symbol_stats = development.groupby("symbol").agg(
        rows=("event_key", "size"), mean_r_24bp=("r_24bp", "mean"),
        mean_robust_utility=("robust_utility", "mean"),
    ).reset_index()
    allowed_symbols = sorted(symbol_stats.loc[
        (symbol_stats.rows >= 10) & (symbol_stats.mean_r_24bp > 0), "symbol"
    ].tolist())
    if not allowed_symbols:
        allowed_symbols = list(SYMBOLS)

    paths = []
    ledgers = []
    for name, allowed in (("all_four", set(SYMBOLS)), ("development_positive_symbols", set(allowed_symbols))):
        rows, frames = evaluate_policy(
            name, events, candidate_value, minute, funding, costs, engine, fifteen, promotions,
            audit, DEVELOPMENT_START, DEVELOPMENT_END, allowed_symbols=allowed,
        )
        paths.extend(rows); ledgers.extend(frames)
        rows, frames = evaluate_policy(
            name, events, candidate_value, minute, funding, costs, engine, fifteen, promotions,
            audit, DEVELOPMENT_END, CONFIRMATION_END, allowed_symbols=allowed,
        )
        paths.extend(rows); ledgers.extend(frames)

    validation_models = fit_models(early, columns)
    final_models = fit_models(development, columns)
    diagnostics: dict[str, Any] = {}
    for model_name, model in validation_models.items():
        diagnostics[model_name] = {"2022_forward": model_diagnostics(model_name, model, late, columns)}
        score = model_scores(model_name, model, late, columns)
        score_map = dict(zip(late.event_key, score))
        rows, frames = evaluate_policy(
            f"{model_name}_2022_forward", events, candidate_value, minute, funding, costs,
            engine, fifteen, promotions, audit, VALIDATION_SPLIT, DEVELOPMENT_END,
            score_by_key=score_map,
        )
        paths.extend(rows); ledgers.extend(frames)

    for model_name, model in final_models.items():
        diagnostics.setdefault(model_name, {})["frozen_2023"] = model_diagnostics(model_name, model, confirmation, columns)
        score = model_scores(model_name, model, confirmation, columns)
        score_map = dict(zip(confirmation.event_key, score))
        rows, frames = evaluate_policy(
            f"{model_name}_frozen_2023", events, candidate_value, minute, funding, costs,
            engine, fifteen, promotions, audit, DEVELOPMENT_END, CONFIRMATION_END,
            score_by_key=score_map,
        )
        paths.extend(rows); ledgers.extend(frames)

    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_parquet(args.output / "POLICY_TRADE_LEDGER.parquet", index=False)

    confirmation_rows = [
        row for row in paths
        if row["period_start"].startswith("2023-01-01") and row["cost"] in {"15bp", "18bp", "24bp"}
    ]
    survivors = []
    by_policy: dict[str, dict[str, dict[str, Any]]] = {}
    for row in confirmation_rows:
        by_policy.setdefault(row["policy"], {})[row["cost"]] = row
    for policy, group in by_policy.items():
        if not all(cost in group for cost in COST_NAMES):
            continue
        if (
            group["15bp"]["trade_count"] >= 30
            and group["15bp"]["total_return"] > 0
            and group["18bp"]["total_return"] > 0
            and group["15bp"]["profit_factor"] > 1
            and group["18bp"]["profit_factor"] > 1
            and group["15bp"]["top5_positive_share"] < 0.35
            and group["24bp"]["total_return"] > -0.02
        ):
            survivors.append({
                "policy": policy,
                "15bp_return": group["15bp"]["total_return"],
                "18bp_return": group["18bp"]["total_return"],
                "24bp_return": group["24bp"]["total_return"],
                "trades": group["15bp"]["trade_count"],
                "top5_share": group["15bp"]["top5_positive_share"],
                "winner_reroute_15bp": group["15bp"]["winner_reroute"]["total_return"],
            })
    survivors.sort(key=lambda row: (row["18bp_return"], row["15bp_return"]), reverse=True)
    decision = {
        "status": "PRE2024_POLICY_SURVIVOR_REQUIRES_BYBIT_TRANSPORT" if survivors else "RETIRED_POLICY_REFINEMENT_FAILURE_PRE2024",
        "survivors": survivors,
        "official_2024_opened": False,
        "risk_leverage_search_opened": False,
        "ranking_changed": False,
    }
    result = {
        "schema_version": 1,
        "result_id": "RES-20260730-ALIGNED-CONTINUATION-POLICY-001",
        "claim_id": "CLM-20260730-ALIGNED-CONTINUATION-AUDIT-001",
        "candidate_id": candidate_value.candidate_id,
        "event_rows": len(table),
        "feature_columns": columns,
        "development_symbol_rule": {
            "rule": "allow symbols with at least 10 development events and positive independent mean 24bp R",
            "allowed_symbols": allowed_symbols,
            "statistics": symbol_stats.to_dict("records"),
        },
        "model_diagnostics": diagnostics,
        "paths": paths,
        "decision": decision,
        "winner_deletion_semantics": "remove selected event, then reroute the same timestamp to the next eligible candidate; diagnostic only",
        "orders_submitted": False,
    }
    (args.output / "POLICY_RESULT.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (args.output / "POLICY_REPORT.md").write_text(render_report(result), encoding="utf-8")
    print(json.dumps({"decision": decision, "allowed_symbols": allowed_symbols}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
