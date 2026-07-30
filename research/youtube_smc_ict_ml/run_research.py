#!/usr/bin/env python3
"""Prepare on pre-2024 data and causally evaluate the selected system on 2024H1."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import math
import platform
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from research.youtube_smc_ict_ml.system import (
    FeeExecutionConfig,
    ModelConfig,
    StructuralConfig,
    add_cross_asset_features,
    build_symbol_features,
    build_trade_plans,
    candidates_frame,
    choose_calibrated_policy,
    feature_columns,
    fit_ranker,
    generate_candidates,
    load_symbol_data,
    plans_frame,
    quantile_threshold,
    run_single_slot_backtest,
    save_backtest_result,
    score_rows,
    utc_ms,
)

LOGGER = logging.getLogger("youtube_smc_ict_ml")

SEGMENTS = ("PRE_2024_2021", "PRE_2024_2022", "PRE_2024_2023", "2024_H1")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TRAIN_CUTOFF_MS = utc_ms("2023-07-01T00:00:00Z")
CALIBRATION_START_MS = TRAIN_CUTOFF_MS
PREP_CUTOFF_MS = utc_ms("2024-01-01T00:00:00Z")
EVALUATION_START_MS = PREP_CUTOFF_MS
EVALUATION_END_MS = utc_ms("2024-07-01T00:00:00Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def structural_grid() -> dict[str, StructuralConfig]:
    """Small predeclared family around one SMC/ICT logic, not strategy hopping."""
    return {
        "core_fast_confirmation": StructuralConfig(
            pivot_left=2,
            pivot_right=2,
            sweep_min_depth_atr=0.015,
            sweep_max_age_bars=2,
            internal_structure_lookback=4,
            displacement_body_atr=0.36,
            displacement_range_atr=0.62,
            displacement_close_location=0.64,
            stop_buffer_atr=0.06,
            min_target_distance_atr=0.60,
            min_rr=0.75,
        ),
        "core_balanced": StructuralConfig(),
        "core_strict_displacement": StructuralConfig(
            pivot_left=4,
            pivot_right=4,
            sweep_min_depth_atr=0.05,
            sweep_max_age_bars=4,
            internal_structure_lookback=6,
            displacement_body_atr=0.62,
            displacement_range_atr=0.92,
            displacement_close_location=0.76,
            stop_buffer_atr=0.10,
            min_target_distance_atr=1.0,
            min_rr=1.15,
        ),
    }


def candidate_counts(rows: pd.DataFrame) -> dict[str, Any]:
    if rows.empty:
        return {"total": 0}
    return {
        "total": int(len(rows)),
        "by_symbol": rows.groupby("symbol").size().astype(int).to_dict(),
        "by_entry_mode": rows.groupby("entry_mode").size().astype(int).to_dict(),
        "by_direction": rows.groupby("direction").size().astype(int).to_dict(),
        "resolved_executed": int((rows["resolved"].fillna(False) & rows["executed"].fillna(False)).sum()),
        "canceled": int((rows["resolved"].fillna(False) & ~rows["executed"].fillna(False)).sum()),
        "unresolved": int((~rows["resolved"].fillna(False)).sum()),
    }


def calibration_order_key(run: dict[str, Any]) -> tuple[float, float, float, int]:
    policy = run["policy"]
    summary = policy["calibration_summary"]
    robust = float(policy.get("stressed_daily_growth", -math.inf))
    return (
        1.0 if policy.get("alpha_confirmed") else 0.0,
        robust,
        float(summary.get("daily_geometric_growth", -math.inf)),
        int(summary.get("executed_trades", 0)),
    )


def feature_importance_table(ranker: Any, rows: pd.DataFrame, *, max_rows: int = 3000) -> pd.DataFrame:
    eligible = rows[
        rows["executed"].fillna(False).astype(bool)
        & rows["resolved"].fillna(False).astype(bool)
        & rows["net_r"].notna()
        & (rows["signal_available_ms"] >= CALIBRATION_START_MS)
        & (rows["signal_available_ms"] < PREP_CUTOFF_MS)
        & (rows["exit_time_ms"].fillna(PREP_CUTOFF_MS + 1) < PREP_CUTOFF_MS)
    ].copy()
    if len(eligible) < 30:
        return pd.DataFrame(columns=["feature", "importance_mean", "importance_std"])
    if len(eligible) > max_rows:
        eligible = eligible.sample(max_rows, random_state=20260727)
    x = ranker.encoder.transform(eligible[feature_columns(eligible)])
    y = eligible["net_r"].clip(-3.0, 8.0).to_numpy(float)
    result = permutation_importance(
        ranker.model,
        x,
        y,
        n_repeats=5,
        random_state=20260727,
        scoring="neg_mean_squared_error",
    )
    table = pd.DataFrame(
        {
            "feature": ranker.encoder.columns_,
            "importance_mean": result.importances_mean,
            "importance_std": result.importances_std,
        }
    )
    return table.sort_values("importance_mean", ascending=False).reset_index(drop=True)


def run(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Loading canonical data from %s", data_root)
    symbol_data = {
        symbol: load_symbol_data(data_root, symbol=symbol, segments=SEGMENTS)
        for symbol in SYMBOLS
    }
    execution = FeeExecutionConfig()
    model_config = ModelConfig(monthly_refit=False)
    config_runs: list[dict[str, Any]] = []
    retained: dict[str, dict[str, Any]] = {}

    for config_name, structural in structural_grid().items():
        LOGGER.info("Building SMC/ICT candidates for %s", config_name)
        feature_frames = {
            symbol: build_symbol_features(data, structural)
            for symbol, data in symbol_data.items()
        }
        feature_frames = add_cross_asset_features(feature_frames)
        candidates = []
        for symbol in SYMBOLS:
            generated = generate_candidates(feature_frames[symbol], structural)
            LOGGER.info("%s %s candidates: %d", config_name, symbol, len(generated))
            candidates.extend(generated)
        plans = build_trade_plans(
            candidates,
            symbol_data,
            execution,
            end_exclusive_ms=EVALUATION_END_MS,
        )
        rows = plans_frame(plans)
        if rows.empty:
            LOGGER.warning("%s generated no plans", config_name)
            continue
        try:
            calibration_ranker = fit_ranker(rows, cutoff_ms=TRAIN_CUTOFF_MS, model_config=model_config)
        except ValueError as exc:
            LOGGER.warning("Skipping %s: %s", config_name, exc)
            continue
        rows["score"] = np.nan
        calibration_mask = (
            (rows["activation_ms"] >= CALIBRATION_START_MS)
            & (rows["activation_ms"] < PREP_CUTOFF_MS)
        )
        rows.loc[calibration_mask, "score"] = score_rows(calibration_ranker, rows.loc[calibration_mask]).to_numpy()
        policy, calibration_table = choose_calibrated_policy(
            rows,
            {plan.candidate.candidate_id: plan for plan in plans},
            symbol_data,
            execution,
            calibration_start_ms=CALIBRATION_START_MS,
            calibration_end_exclusive_ms=PREP_CUTOFF_MS,
        )
        config_dir = output / "structural_search" / config_name
        config_dir.mkdir(parents=True, exist_ok=True)
        calibration_table.to_csv(config_dir / "calibration_grid.csv", index=False)
        (config_dir / "policy.json").write_text(
            json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        run_record = {
            "config_name": config_name,
            "structural_config": dataclasses.asdict(structural),
            "policy": policy,
            "candidate_counts": candidate_counts(rows),
            "calibration_training_rows": calibration_ranker.training_rows,
        }
        config_runs.append(run_record)
        retained[config_name] = {
            "features": feature_frames,
            "candidates": candidates,
            "plans": plans,
            "rows": rows,
            "calibration_ranker": calibration_ranker,
        }
        LOGGER.info("%s calibration: %s", config_name, policy["calibration_summary"])

    if not config_runs:
        raise RuntimeError("No structural configuration produced a trainable model")
    best_record = max(config_runs, key=calibration_order_key)
    best_name = str(best_record["config_name"])
    best = retained[best_name]
    rows = best["rows"].copy()
    plans = best["plans"]
    plans_by_id = {plan.candidate.candidate_id: plan for plan in plans}
    policy = best_record["policy"]

    LOGGER.info("Selected pre-2024 structural configuration: %s", best_name)
    final_ranker = fit_ranker(rows, cutoff_ms=PREP_CUTOFF_MS, model_config=model_config)
    pre2024_mask = rows["activation_ms"] < PREP_CUTOFF_MS
    pre2024_scores = score_rows(final_ranker, rows.loc[pre2024_mask])
    rows.loc[pre2024_mask, "final_score"] = pre2024_scores.to_numpy()
    evaluation_mask = (
        (rows["activation_ms"] >= EVALUATION_START_MS)
        & (rows["activation_ms"] < EVALUATION_END_MS)
    )
    rows.loc[evaluation_mask, "final_score"] = score_rows(final_ranker, rows.loc[evaluation_mask]).to_numpy()
    rows["score"] = rows["final_score"]
    score_quantile = float(policy["score_quantile"])
    causal_threshold_pool = rows[
        (rows["activation_ms"] >= CALIBRATION_START_MS)
        & (rows["activation_ms"] < PREP_CUTOFF_MS)
        & rows["score"].notna()
    ]
    evaluation_threshold = quantile_threshold(causal_threshold_pool, score_quantile)
    risk_fraction = float(policy["risk_fraction"])

    h1 = run_single_slot_backtest(
        rows,
        plans_by_id,
        symbol_data,
        execution,
        start_ms=EVALUATION_START_MS,
        end_exclusive_ms=EVALUATION_END_MS,
        risk_fraction=risk_fraction,
        score_threshold=evaluation_threshold,
        score_quantile=score_quantile,
        initial_nav=10_000.0,
    )
    h1_one_percent_risk = run_single_slot_backtest(
        rows,
        plans_by_id,
        symbol_data,
        execution,
        start_ms=EVALUATION_START_MS,
        end_exclusive_ms=EVALUATION_END_MS,
        risk_fraction=0.01,
        score_threshold=evaluation_threshold,
        score_quantile=score_quantile,
        initial_nav=10_000.0,
    )
    h1_stress = run_single_slot_backtest(
        rows,
        plans_by_id,
        symbol_data,
        execution.stressed(1.35),
        start_ms=EVALUATION_START_MS,
        end_exclusive_ms=EVALUATION_END_MS,
        risk_fraction=risk_fraction,
        score_threshold=evaluation_threshold,
        score_quantile=score_quantile,
        initial_nav=10_000.0,
    )

    save_backtest_result(h1, output, "2024H1_selected")
    save_backtest_result(h1_one_percent_risk, output, "2024H1_fixed_1pct_risk")
    save_backtest_result(h1_stress, output, "2024H1_cost_stress_1p35x")
    rows.to_csv(output / "candidate_plans_and_scores.csv.gz", index=False, compression="gzip")
    candidate_meta = candidates_frame(best["candidates"])
    candidate_meta.to_csv(output / "candidate_features.csv.gz", index=False, compression="gzip")
    importance = feature_importance_table(final_ranker, rows)
    importance.to_csv(output / "feature_importance.csv", index=False)
    joblib.dump(
        {
            "ranker": final_ranker,
            "structural_config": best_record["structural_config"],
            "execution_config": dataclasses.asdict(execution),
            "model_config": dataclasses.asdict(model_config),
            "score_quantile": score_quantile,
            "score_threshold": evaluation_threshold,
            "risk_fraction": risk_fraction,
            "training_cutoff_ms": PREP_CUTOFF_MS,
        },
        output / "prepared_model.joblib",
        compress=3,
    )

    result = {
        "schema_version": 1,
        "result_id": f"R-YT-SMC-ICT-ML-2024H1-{best_name}",
        "validation_stage": "2024H1 causal one-minute execution evaluation",
        "selected_structural_config": best_name,
        "structural_config": best_record["structural_config"],
        "model_config": dataclasses.asdict(model_config),
        "execution_config": dataclasses.asdict(execution),
        "segments": list(SEGMENTS),
        "symbols": list(SYMBOLS),
        "train_cutoff": "2023-07-01T00:00:00Z",
        "calibration_interval": ["2023-07-01T00:00:00Z", "2024-01-01T00:00:00Z"],
        "preparation_cutoff": "2024-01-01T00:00:00Z",
        "evaluation_interval": ["2024-01-01T00:00:00Z", "2024-07-01T00:00:00Z"],
        "latency_ms": 500,
        "score_quantile": score_quantile,
        "evaluation_score_threshold": evaluation_threshold,
        "risk_fraction": risk_fraction,
        "calibration_policy": policy,
        "structural_search": config_runs,
        "selected_candidate_counts": candidate_counts(rows),
        "h1_selected": h1.summary(),
        "h1_fixed_1pct_risk": h1_one_percent_risk.summary(),
        "h1_cost_stress_1p35x": h1_stress.summary(),
        "target_daily_geometric_growth": 0.01,
        "target_met_in_h1": bool(h1.daily_geometric_growth >= 0.01),
        "fatal_liquidation": bool(h1.liquidation_count > 0),
        "causal_notes": [
            "All candidate features are computed from completed observations available by signal_available_ms.",
            "Confirmed pivots become visible only after their right-side confirmation span.",
            "New orders activate 500 ms after the completed signal bar and, at one-minute resolution, fill no earlier than the next observable minute.",
            "Same-minute target/stop ambiguity is resolved as stop first.",
            "No pending-order timeout or forced position time exit is used.",
            "The ML model and policy are selected using only outcomes resolved before 2024-01-01.",
        ],
        "software": {
            "python": sys.version,
            "platform": platform.platform(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
    }
    result_path = output / "RESULT.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Transcript-grounded SMC/ICT ML — 2024H1 result",
        "",
        f"- Result ID: `{result['result_id']}`",
        f"- Selected structure: `{best_name}`",
        f"- Validation stage: {result['validation_stage']}",
        f"- Daily geometric NAV growth: **{h1.daily_geometric_growth:.6%}**",
        f"- Terminal NAV: **{h1.terminal_nav:,.2f} USDT**",
        f"- Account multiple: **{h1.terminal_nav / h1.initial_nav:.4f}x**",
        f"- Maximum UTC-day drawdown: **{h1.max_drawdown:.2%}**",
        f"- Executed trades: **{h1.executed_trades}**",
        f"- Liquidations: **{h1.liquidation_count}**",
        f"- 1.35× cost-stress daily growth: **{h1_stress.daily_geometric_growth:.6%}**",
        f"- Target met in H1: **{result['target_met_in_h1']}**",
        "",
        "## Core sequence",
        "",
        "A candidate exists only after a confirmed liquidity level is swept and reclaimed, directional displacement closes through internal structure, and the opposing liquidity objective provides a valid stop-to-target geometry. FVG/order-block locations choose execution price; they do not create standalone signals. The ML model ranks valid candidates rather than redefining SMC/ICT semantics.",
        "",
        "## Evaluation boundaries",
        "",
        "The structure family, feature set, model hyperparameters, cost model, and policy search are completed on data available through 2023-12-31. 2024H1 is then replayed causally with a continuous 10,000 USDT account and one global position/order slot.",
    ]
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    manifest_files = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            manifest_files.append({
                "path": str(path.relative_to(output)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    (output / "ARTIFACT_MANIFEST.json").write_text(
        json.dumps({"schema_version": 1, "files": manifest_files}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksums = [f"{sha256_file(path)}  {path.relative_to(output)}" for path in sorted(output.rglob("*")) if path.is_file() and path.name != "SHA256SUMS"]
    (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    LOGGER.info("2024H1 result: %s", h1.summary())
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    try:
        return run(args)
    except Exception:
        LOGGER.exception("Research run failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
