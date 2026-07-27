from __future__ import annotations

import argparse
import itertools
import json
import math
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from smc_backtest import (
    MODEL_VARIANTS,
    StrategyFilter,
    attach_net_labels,
    compact_metrics,
    filter_candidates,
    simulate_account,
    walk_forward_scores,
)
from smc_core import (
    FEATURE_COLUMNS,
    add_cross_market_context,
    generate_candidates,
    load_market_data,
    prepare_symbol_frame,
)

SYSTEM_ID = "YT-SMC-ICT-CAUSAL-ML-GPT56-001"
VALIDATION_START = "2023-01-01T00:00:00Z"
VALIDATION_END = "2024-01-01T00:00:00Z"
EVALUATION_START = "2024-01-01T00:00:00Z"
H1_END = "2024-07-01T00:00:00Z"
EVALUATION_END = "2026-07-01T00:00:00Z"


def parse_utc(value: str) -> int:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return int(timestamp.timestamp() * 1000)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def strategy_from_row(row: pd.Series) -> StrategyFilter:
    return StrategyFilter(
        model_variant=int(row["model_variant"]),
        score_threshold=float(row["score_threshold"]),
        rr_min=float(row["rr_min"]),
        entry_variant=str(row["entry_variant"]),
        require_smt=bool(row["require_smt"]),
        require_cisd=bool(row["require_cisd"]),
        session_scope=str(row["session_scope"]),
    )


def validation_grid(
    candidates: pd.DataFrame,
    markets: dict[str, Any],
    prepared: dict[str, pd.DataFrame],
    *,
    start_ms: int,
    end_ms: int,
) -> tuple[pd.DataFrame, dict[int, list[dict[str, Any]]]]:
    rows: list[dict[str, Any]] = []
    model_audits: dict[int, list[dict[str, Any]]] = {}
    validation_mask = (
        (candidates["signal_timestamp_ms"] >= start_ms)
        & (candidates["signal_timestamp_ms"] < end_ms)
    )
    for model_variant, params in enumerate(MODEL_VARIANTS):
        score_column = f"score_validation_m{model_variant}"
        scores, audits = walk_forward_scores(
            candidates,
            start_ms=start_ms,
            end_ms=end_ms,
            model_params=params,
        )
        candidates[score_column] = scores
        model_audits[model_variant] = audits
        valid_scores = candidates.loc[validation_mask, score_column].dropna()
        if valid_scores.empty:
            continue
        threshold_values = sorted(
            set(float(valid_scores.quantile(quantile)) for quantile in (0.55, 0.70, 0.82, 0.90))
        )
        combinations = itertools.product(
            threshold_values,
            (1.0, 1.5, 2.0),
            ("fvg_midpoint", "fvg_orderblock_overlap"),
            (False, True),
            (False, True),
            ("all", "london_newyork"),
        )
        for threshold, rr_min, entry_variant, require_smt, require_cisd, session_scope in combinations:
            strategy = StrategyFilter(
                model_variant=model_variant,
                score_threshold=threshold,
                rr_min=rr_min,
                entry_variant=entry_variant,
                require_smt=require_smt,
                require_cisd=require_cisd,
                session_scope=session_scope,
            )
            eligible = filter_candidates(candidates, strategy, score_column)
            metrics = simulate_account(
                eligible,
                markets,
                prepared,
                period_start_ms=start_ms,
                period_end_ms=end_ms,
                score_column=score_column,
                risk_fraction=0.01,
                leverage=20.0,
            )
            rows.append(
                {
                    **asdict(strategy),
                    "score_column": score_column,
                    "eligible_candidates": int(
                        (
                            (eligible["signal_timestamp_ms"] >= start_ms)
                            & (eligible["signal_timestamp_ms"] < end_ms)
                        ).sum()
                    ),
                    **compact_metrics(metrics),
                }
            )
    grid = pd.DataFrame(rows)
    if grid.empty:
        raise RuntimeError("validation grid produced no configurations")
    return grid, model_audits


def evaluate_stability(
    grid: pd.DataFrame,
    candidates: pd.DataFrame,
    markets: dict[str, Any],
    prepared: dict[str, pd.DataFrame],
    *,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    midpoint = parse_utc("2023-07-01T00:00:00Z")
    eligible_grid = grid[
        (~grid["liquidated"])
        & (grid["completed_trades"] >= 8)
        & (grid["final_nav"] > 0.0)
    ].copy()
    if eligible_grid.empty:
        eligible_grid = grid[grid["final_nav"] > 0.0].copy()
    top = eligible_grid.nlargest(min(40, len(eligible_grid)), "geometric_daily_growth")
    stable_rows: list[dict[str, Any]] = []
    for _, row in top.iterrows():
        strategy = strategy_from_row(row)
        score_column = str(row["score_column"])
        eligible = filter_candidates(candidates, strategy, score_column)
        h1 = simulate_account(
            eligible,
            markets,
            prepared,
            period_start_ms=start_ms,
            period_end_ms=midpoint,
            score_column=score_column,
            risk_fraction=0.01,
            leverage=20.0,
        )
        h2 = simulate_account(
            eligible,
            markets,
            prepared,
            period_start_ms=midpoint,
            period_end_ms=end_ms,
            score_column=score_column,
            risk_fraction=0.01,
            leverage=20.0,
        )
        full_growth = float(row["geometric_daily_growth"])
        min_half = min(float(h1["geometric_daily_growth"]), float(h2["geometric_daily_growth"]))
        objective = full_growth + 0.20 * min_half - 0.001 * float(row["max_drawdown"])
        stable_rows.append(
            {
                **row.to_dict(),
                "h1_geometric_daily_growth": h1["geometric_daily_growth"],
                "h2_geometric_daily_growth": h2["geometric_daily_growth"],
                "h1_completed_trades": h1["completed_trades"],
                "h2_completed_trades": h2["completed_trades"],
                "selection_objective": objective,
            }
        )
    stable = pd.DataFrame(stable_rows).sort_values("selection_objective", ascending=False).reset_index(drop=True)
    if stable.empty:
        raise RuntimeError("no validation configuration survived basic account integrity")
    return stable


def optimize_risk(
    selected: pd.Series,
    candidates: pd.DataFrame,
    markets: dict[str, Any],
    prepared: dict[str, pd.DataFrame],
    *,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    strategy = strategy_from_row(selected)
    score_column = str(selected["score_column"])
    eligible = filter_candidates(candidates, strategy, score_column)
    midpoint = parse_utc("2023-07-01T00:00:00Z")
    rows: list[dict[str, Any]] = []
    risk_values = (0.005, 0.01)
    if float(selected["geometric_daily_growth"]) > 0.0:
        risk_values = (0.005, 0.01, 0.02, 0.04, 0.07, 0.10, 0.15)
    for risk_fraction, leverage in itertools.product(risk_values, (10.0, 25.0, 50.0, 100.0)):
        full = simulate_account(
            eligible,
            markets,
            prepared,
            period_start_ms=start_ms,
            period_end_ms=end_ms,
            score_column=score_column,
            risk_fraction=risk_fraction,
            leverage=leverage,
        )
        h1 = simulate_account(
            eligible,
            markets,
            prepared,
            period_start_ms=start_ms,
            period_end_ms=midpoint,
            score_column=score_column,
            risk_fraction=risk_fraction,
            leverage=leverage,
        )
        h2 = simulate_account(
            eligible,
            markets,
            prepared,
            period_start_ms=midpoint,
            period_end_ms=end_ms,
            score_column=score_column,
            risk_fraction=risk_fraction,
            leverage=leverage,
        )
        min_half = min(float(h1["geometric_daily_growth"]), float(h2["geometric_daily_growth"]))
        objective = float(full["geometric_daily_growth"]) + 0.20 * min_half - 0.001 * float(full["max_drawdown"])
        rows.append(
            {
                "risk_fraction": risk_fraction,
                "leverage": leverage,
                **compact_metrics(full),
                "h1_geometric_daily_growth": h1["geometric_daily_growth"],
                "h2_geometric_daily_growth": h2["geometric_daily_growth"],
                "selection_objective": objective,
            }
        )
    result = pd.DataFrame(rows)
    viable = result[(~result["liquidated"]) & (result["final_nav"] > 0.0) & (result["max_drawdown"] < 0.98)]
    if viable.empty:
        viable = result[(~result["liquidated"]) & (result["final_nav"] > 0.0)]
    if viable.empty:
        viable = result
    order = viable.sort_values("selection_objective", ascending=False).index.tolist()
    remaining = [idx for idx in result.index if idx not in order]
    return result.loc[order + remaining].reset_index(drop=True)


def half_year_metrics(full_result: dict[str, Any]) -> list[dict[str, Any]]:
    daily = pd.DataFrame(full_result["daily_nav"])
    if daily.empty:
        return []
    initial_nav = float(full_result["initial_nav"])
    daily["timestamp"] = pd.to_datetime(daily["timestamp_ms"], unit="ms", utc=True)
    boundaries = [
        ("2024H1", "2024-01-01", "2024-07-01"),
        ("2024H2", "2024-07-01", "2025-01-01"),
        ("2025H1", "2025-01-01", "2025-07-01"),
        ("2025H2", "2025-07-01", "2026-01-01"),
        ("2026H1", "2026-01-01", "2026-07-01"),
    ]
    out: list[dict[str, Any]] = []
    prior_end_nav = initial_nav
    trades = full_result["trades"]
    for label, start_text, end_text in boundaries:
        start = pd.Timestamp(start_text, tz="UTC")
        end = pd.Timestamp(end_text, tz="UTC")
        segment = daily[(daily["timestamp"] > start) & (daily["timestamp"] <= end)].copy()
        if segment.empty:
            continue
        values = np.array([prior_end_nav] + segment["nav"].astype(float).tolist())
        end_nav = float(values[-1])
        days = int((end - start).days)
        growth = math.exp(math.log(end_nav / prior_end_nav) / days) - 1.0 if end_nav > 0 and prior_end_nav > 0 else -1.0
        peaks = np.maximum.accumulate(values)
        max_dd = float(-(values / peaks - 1.0).min())
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        completed = sum(start_ms <= int(trade["exit_timestamp_ms"]) < end_ms and trade["completed"] for trade in trades)
        out.append(
            {
                "half": label,
                "start_nav": prior_end_nav,
                "end_nav": end_nav,
                "account_multiple": end_nav / prior_end_nav if prior_end_nav > 0 else 0.0,
                "geometric_daily_growth": growth,
                "max_drawdown_within_half": max_dd,
                "completed_trades": completed,
            }
        )
        prior_end_nav = end_nav
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    markets = load_market_data(args.data_root)
    prepared: dict[str, pd.DataFrame] = {}
    for symbol, market in markets.items():
        print(f"Preparing causal SMC features: {symbol} rows={len(market.frame)}", flush=True)
        prepared[symbol] = prepare_symbol_frame(market.frame, swing_radius=args.swing_radius)
    prepared = add_cross_market_context(prepared)
    print("Generating liquidity-sweep/displacement/FVG candidates", flush=True)
    candidates = generate_candidates(
        prepared,
        max_sweep_age_bars=args.max_sweep_age_bars,
        stop_buffers_atr=(0.05, 0.15),
    )
    if candidates.empty:
        raise RuntimeError("structural engine generated zero candidates")
    print(f"Candidates generated: {len(candidates)}", flush=True)
    candidates = attach_net_labels(candidates, markets, prepared)
    candidates.to_parquet(output / "CANDIDATES.parquet", index=False, compression="zstd")
    label_summary = {
        "candidates": int(len(candidates)),
        "valid_labels": int(candidates["label_valid"].sum()),
        "hypothetical_fills": int(candidates["filled_hypothetical"].sum()),
        "positive_labels": int((candidates["net_r_label"] > 0).sum()),
        "mean_net_r": float(candidates.loc[candidates["label_valid"], "net_r_label"].mean()),
        "median_net_r": float(candidates.loc[candidates["label_valid"], "net_r_label"].median()),
    }
    print(json.dumps(json_safe(label_summary), ensure_ascii=False, indent=2), flush=True)

    validation_start = parse_utc(VALIDATION_START)
    validation_end = parse_utc(VALIDATION_END)
    grid, validation_model_audits = validation_grid(
        candidates,
        markets,
        prepared,
        start_ms=validation_start,
        end_ms=validation_end,
    )
    grid.to_csv(output / "VALIDATION_GRID.csv", index=False)
    stable = evaluate_stability(
        grid,
        candidates,
        markets,
        prepared,
        start_ms=validation_start,
        end_ms=validation_end,
    )
    stable.to_csv(output / "VALIDATION_STABILITY.csv", index=False)
    selected_validation = stable.iloc[0]
    selected_strategy = strategy_from_row(selected_validation)
    risk_grid = optimize_risk(
        selected_validation,
        candidates,
        markets,
        prepared,
        start_ms=validation_start,
        end_ms=validation_end,
    )
    risk_grid.to_csv(output / "RISK_GRID.csv", index=False)
    selected_risk = risk_grid.iloc[0]
    risk_fraction = float(selected_risk["risk_fraction"])
    leverage = float(selected_risk["leverage"])

    evaluation_start = parse_utc(EVALUATION_START)
    h1_end = parse_utc(H1_END)
    evaluation_end = parse_utc(EVALUATION_END)
    selected_model_params = MODEL_VARIANTS[selected_strategy.model_variant]
    evaluation_scores, evaluation_model_audits = walk_forward_scores(
        candidates,
        start_ms=evaluation_start,
        end_ms=evaluation_end,
        model_params=selected_model_params,
    )
    score_column = "score_evaluation_selected"
    candidates[score_column] = evaluation_scores
    selected_candidates = filter_candidates(candidates, selected_strategy, score_column)

    h1_result = simulate_account(
        selected_candidates,
        markets,
        prepared,
        period_start_ms=evaluation_start,
        period_end_ms=h1_end,
        score_column=score_column,
        risk_fraction=risk_fraction,
        leverage=leverage,
    )
    full_result = simulate_account(
        selected_candidates,
        markets,
        prepared,
        period_start_ms=evaluation_start,
        period_end_ms=evaluation_end,
        score_column=score_column,
        risk_fraction=risk_fraction,
        leverage=leverage,
    )

    ablations: list[dict[str, Any]] = []
    ablation_filters = {
        "selected": selected_strategy,
        "no_smt_requirement": StrategyFilter(**{**asdict(selected_strategy), "require_smt": False}),
        "no_cisd_requirement": StrategyFilter(**{**asdict(selected_strategy), "require_cisd": False}),
        "all_sessions": StrategyFilter(**{**asdict(selected_strategy), "session_scope": "all"}),
        "lower_score_gate": StrategyFilter(
            **{
                **asdict(selected_strategy),
                "score_threshold": float(
                    candidates.loc[
                        (candidates["signal_timestamp_ms"] >= evaluation_start)
                        & (candidates["signal_timestamp_ms"] < h1_end),
                        score_column,
                    ].quantile(0.60)
                ),
            }
        ),
    }
    for name, strategy in ablation_filters.items():
        eligible = filter_candidates(candidates, strategy, score_column)
        result = simulate_account(
            eligible,
            markets,
            prepared,
            period_start_ms=evaluation_start,
            period_end_ms=h1_end,
            score_column=score_column,
            risk_fraction=risk_fraction,
            leverage=leverage,
        )
        ablations.append({"name": name, "strategy": asdict(strategy), "metrics": compact_metrics(result)})

    pd.DataFrame(full_result["daily_nav"]).to_csv(output / "FULL_DAILY_NAV.csv", index=False)
    pd.DataFrame(full_result["trades"]).drop(columns=["funding_events"], errors="ignore").to_csv(
        output / "FULL_TRADES.csv", index=False
    )
    pd.DataFrame(full_result["orders"]).to_csv(output / "FULL_ORDERS.csv", index=False)
    pd.DataFrame(h1_result["daily_nav"]).to_csv(output / "H1_DAILY_NAV.csv", index=False)
    write_json(output / "MODEL_AUDIT.json", {"validation": validation_model_audits, "evaluation": evaluation_model_audits})

    summary = {
        "schema_version": 1,
        "system_id": SYSTEM_ID,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": time.time() - started,
        "data_contract": {
            "symbols": sorted(markets),
            "bar_interval": "5m",
            "data_start": "2021-01-01T00:00:00Z",
            "evaluation_start": EVALUATION_START,
            "evaluation_end_exclusive": EVALUATION_END,
            "decision_latency": "500ms represented conservatively by first subsequent 5m bar",
            "global_position_and_pending_entry_slots": 1,
            "daily_boundary": "00:00 UTC",
        },
        "execution_contract": {
            "entry": "resting limit at causal FVG midpoint or FVG/order-block overlap after next-bar activation",
            "maker_fee": 0.0002,
            "taker_fee": 0.00055,
            "slippage": "adverse volatility-scaled 2-12 bps on stop/opposite-delivery/final liquidation value",
            "funding": "actual Bybit historical funding when returned by the public endpoint",
            "same_bar_ambiguity": "stop first",
            "position_exit": "opposing external liquidity, protective stop, or causal opposite delivery; no forced holding-time exit",
            "liquidation_guard": "quantity capped so modeled stop equity exceeds maintenance margin",
        },
        "ml_contract": {
            "features": FEATURE_COLUMNS,
            "model_variant": selected_strategy.model_variant,
            "model_params": selected_model_params,
            "retraining": "monthly walk-forward; training cutoff one hour before month boundary; only fully resolved labels",
            "validation_period": [VALIDATION_START, VALIDATION_END],
            "selection_never_uses_2024_plus": True,
        },
        "label_summary": label_summary,
        "selected_strategy": asdict(selected_strategy),
        "selected_risk": {
            "risk_fraction": risk_fraction,
            "leverage": leverage,
            "validation_metrics": {key: selected_risk[key] for key in risk_grid.columns if key not in {"selection_objective"}},
            "selection_objective": selected_risk["selection_objective"],
        },
        "validation_selection": selected_validation.to_dict(),
        "provisional_2024h1": compact_metrics(h1_result),
        "full_2024_2026": compact_metrics(full_result),
        "half_years_continuous_nav": half_year_metrics(full_result),
        "h1_implementation_ablations": ablations,
        "target_geometric_daily_growth": 0.01,
        "target_met": bool(
            full_result["geometric_daily_growth"] >= 0.01
            and not full_result["liquidated"]
            and full_result["final_nav"] > 0
        ),
    }
    write_json(output / "RUN_SUMMARY.json", summary)
    print(json.dumps(json_safe(summary), ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return summary


def self_test() -> None:
    assert parse_utc("2024-01-01T00:00:00Z") == 1704067200000
    assert json_safe(float("inf")) is None
    print("run_experiment self-test: ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run independent causal ML SMC/ICT system evaluation.")
    parser.add_argument("--data-root", type=Path, default=Path("artifact/bybit_data"))
    parser.add_argument("--output", type=Path, default=Path("artifact/smc_ml_run"))
    parser.add_argument("--swing-radius", type=int, default=6)
    parser.add_argument("--max-sweep-age-bars", type=int, default=12)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
