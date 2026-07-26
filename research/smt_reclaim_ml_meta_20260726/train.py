from __future__ import annotations

import argparse
import json
import math
from datetime import date as date_type
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

CLAIM_ID = "CLM-20260726-SMT-RECLAIM-ML-001"
RESULT_ID = "RES-20260726-SMT-RECLAIM-ML-001"
MODEL_NAMES = ("sparse_logistic_control", "shallow_histogram_gradient_boosting")
QUANTILES = (0.80, 0.90, 0.95)
LATENCIES = (100, 300)
COST_BPS = 24
FEATURE_COLUMNS = (
    "btc_displacement_z",
    "btc_activity_ratio",
    "btc_aggressor_alignment",
    "follower_aggressor_alignment_at_event",
    "horizon_seconds",
    "frozen_beta",
    "initial_residual_gap_bps",
    "overreaction_ratio",
    "target_to_btc_trade_count_ratio_30m",
    "target_to_btc_realized_volatility_ratio_15m",
    "mss_residual_contraction_ratio",
    "milliseconds_event_to_mss",
    "opposite_flow_strength_1s",
    "opposite_flow_trade_count_1s",
    "target_realized_volatility_10s",
    "target_trade_count_1s",
    "other_follower_residual_bps",
    "utc_time_sine",
    "utc_time_cosine",
    "symbol_is_xrp",
)


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def read_matrices(root: Path) -> pd.DataFrame:
    paths = sorted(root.rglob("matrix_*.csv.gz"))
    if not paths:
        raise RuntimeError(f"no matrix files under {root}")
    frames = [pd.read_csv(path, compression="gzip") for path in paths]
    frame = pd.concat(frames, ignore_index=True)
    if frame.empty:
        raise RuntimeError("causal MSS matrix is empty")
    frame["symbol_is_xrp"] = (frame["symbol"].astype(str) == "XRPUSDT").astype(float)
    frame["date"] = frame["date"].astype(str)
    frame["stage"] = frame["stage"].astype(str)
    return frame.sort_values(
        ["confirmation_time", "symbol", "horizon_seconds", "event_id"], kind="stable"
    ).reset_index(drop=True)


def feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in FEATURE_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"missing feature columns: {missing}")
    return frame.loc[:, FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")


def make_model(name: str) -> Pipeline:
    if name == "sparse_logistic_control":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        C=0.2,
                        penalty="l2",
                        class_weight="balanced",
                        max_iter=1000,
                        solver="lbfgs",
                        random_state=20260726,
                    ),
                ),
            ]
        )
    if name == "shallow_histogram_gradient_boosting":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "classifier",
                    HistGradientBoostingClassifier(
                        max_depth=3,
                        max_iter=100,
                        learning_rate=0.05,
                        l2_regularization=1.0,
                        random_state=20260726,
                    ),
                ),
            ]
        )
    raise ValueError(name)


def fit_models(fit: pd.DataFrame) -> tuple[dict[str, dict[int, Pipeline]], dict[str, Any]]:
    models: dict[str, dict[int, Pipeline]] = {name: {} for name in MODEL_NAMES}
    diagnostics: dict[str, Any] = {}
    x_all = feature_frame(fit)
    for name in MODEL_NAMES:
        diagnostics[name] = {}
        for latency in LATENCIES:
            trade_column = f"l{latency}_trade"
            return_column = f"l{latency}_net24_bps"
            executable = fit[trade_column].astype(str).str.lower().isin({"true", "1"})
            executable &= pd.to_numeric(fit[return_column], errors="coerce").notna()
            x = x_all.loc[executable]
            y = (
                pd.to_numeric(fit.loc[executable, return_column], errors="coerce") > 0
            ).astype(int)
            classes = sorted(y.unique().tolist())
            diagnostics[name][str(latency)] = {
                "fit_rows": int(len(y)),
                "positive_labels": int(y.sum()),
                "negative_labels": int((1 - y).sum()),
                "classes": classes,
            }
            if len(y) < 40 or classes != [0, 1]:
                continue
            model = make_model(name)
            model.fit(x, y)
            models[name][latency] = model
    return models, diagnostics


def predict_scores(model: Pipeline, frame: pd.DataFrame) -> np.ndarray:
    scores = model.predict_proba(feature_frame(frame))[:, 1]
    return np.asarray(scores, dtype=np.float64)


def account_return(row: pd.Series | dict[str, Any], latency: int) -> tuple[float, float]:
    gap_fraction = float(row["initial_residual_gap_bps"]) / 10_000.0
    planned_loss_per_notional = 0.5 * gap_fraction + COST_BPS / 10_000.0
    leverage = min(3.0, 0.01 / planned_loss_per_notional)
    gross = float(row[f"l{latency}_gross_bps"])
    value = leverage * (gross - COST_BPS) / 10_000.0
    return max(-0.999999, value), leverage


def selected_rows(
    frame: pd.DataFrame,
    scores: np.ndarray,
    threshold: float,
    latency: int,
) -> tuple[pd.DataFrame, int, int]:
    work = frame.copy()
    work["model_score"] = scores
    selected = work.loc[work["model_score"] >= threshold].copy()
    unavailable_column = f"l{latency}_unavailable"
    unavailable = selected[unavailable_column].astype(str).str.lower().isin({"true", "1"})
    unavailable_count = int(unavailable.sum())
    trade_column = f"l{latency}_trade"
    trade = selected[trade_column].astype(str).str.lower().isin({"true", "1"})
    cancelled_count = int((~trade & ~unavailable).sum())
    potential = selected.loc[trade].copy()
    potential[f"l{latency}_entry_time"] = pd.to_numeric(
        potential[f"l{latency}_entry_time"], errors="coerce"
    )
    potential[f"l{latency}_exit_time"] = pd.to_numeric(
        potential[f"l{latency}_exit_time"], errors="coerce"
    )
    potential = potential.dropna(
        subset=[f"l{latency}_entry_time", f"l{latency}_exit_time", f"l{latency}_gross_bps"]
    )
    return potential, unavailable_count, cancelled_count


def route(
    potential: pd.DataFrame,
    latency: int,
    excluded_event_ids: set[str] | None = None,
) -> pd.DataFrame:
    excluded = excluded_event_ids or set()
    work = potential.loc[~potential["event_id"].astype(str).isin(excluded)].copy()
    accepted: list[int] = []
    for stage_date in sorted(work["date"].astype(str).unique()):
        day = work.loc[work["date"].astype(str) == stage_date].copy()
        day = day.sort_values(
            [
                f"l{latency}_entry_time",
                "model_score",
                "initial_residual_gap_bps",
                "btc_displacement_z",
                "symbol",
                "event_id",
            ],
            ascending=[True, False, False, False, True, True],
            kind="stable",
        )
        slot_free = -math.inf
        for index, row in day.iterrows():
            entry = float(row[f"l{latency}_entry_time"])
            if entry <= slot_free:
                continue
            accepted.append(index)
            slot_free = float(row[f"l{latency}_exit_time"])
    if not accepted:
        return work.iloc[0:0].copy()
    return work.loc[accepted].sort_values(
        [f"l{latency}_entry_time", "event_id"], kind="stable"
    ).reset_index(drop=True)


def winner_exclusions(routed: pd.DataFrame, latency: int) -> set[str]:
    if routed.empty:
        return set()
    positive: list[tuple[float, str]] = []
    for _, row in routed.iterrows():
        value, _ = account_return(row, latency)
        if value > 0:
            positive.append((value, str(row["event_id"])))
    positive.sort(reverse=True)
    remove_count = int(math.ceil(0.10 * len(routed)))
    return {event_id for _, event_id in positive[:remove_count]}


def metrics(
    routed: pd.DataFrame,
    latency: int,
    stage_dates: list[str],
    unavailable_selected: int,
    cancelled_selected: int,
) -> dict[str, Any]:
    nav = 1.0
    peak = 1.0
    maximum_drawdown = 0.0
    account_returns: list[float] = []
    leverages: list[float] = []
    net_bps: list[float] = []
    daily_factor = {value: 1.0 for value in stage_dates}
    for _, row in routed.iterrows():
        value, leverage = account_return(row, latency)
        account_returns.append(value)
        leverages.append(leverage)
        net_bps.append(float(row[f"l{latency}_gross_bps"]) - COST_BPS)
        nav *= 1.0 + value
        daily_factor[str(row["date"])] *= 1.0 + value
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, 1.0 - nav / peak)
    net = np.asarray(net_bps, dtype=np.float64)
    positive = np.asarray([value for value in account_returns if value > 0], dtype=np.float64)
    negative = np.asarray([value for value in account_returns if value < 0], dtype=np.float64)
    profit_factor = (
        float(positive.sum() / abs(negative.sum()))
        if len(negative)
        else (999.0 if len(positive) else 0.0)
    )
    top_five_share = (
        float(np.sort(positive)[-5:].sum() / positive.sum())
        if len(positive) and positive.sum() > 0
        else 1.0
    )
    span_days = (
        (date_type.fromisoformat(max(stage_dates)) - date_type.fromisoformat(min(stage_dates))).days + 1
    )
    return {
        "trade_count": int(len(routed)),
        "selected_unavailable_count": int(unavailable_selected),
        "selected_cancelled_before_entry_count": int(cancelled_selected),
        "mean_net_bps": float(net.mean()) if len(net) else None,
        "median_net_bps": float(np.median(net)) if len(net) else None,
        "profit_factor": profit_factor,
        "total_return": nav - 1.0,
        "geometric_growth_per_sample_day": nav ** (1.0 / len(stage_dates)) - 1.0 if nav > 0 else -1.0,
        "geometric_growth_per_calendar_span_day": nav ** (1.0 / span_days) - 1.0 if nav > 0 else -1.0,
        "maximum_drawdown": maximum_drawdown,
        "positive_dates": int(sum(value > 1.0 for value in daily_factor.values())),
        "positive_date_fraction": float(sum(value > 1.0 for value in daily_factor.values()) / len(stage_dates)),
        "daily_returns": {key: value - 1.0 for key, value in daily_factor.items()},
        "top_five_positive_pnl_share": top_five_share,
        "median_leverage": float(np.median(leverages)) if leverages else 0.0,
    }


def evaluate(
    frame: pd.DataFrame,
    scores: np.ndarray,
    threshold: float,
    latency: int,
    stage_dates: list[str],
) -> dict[str, Any]:
    potential, unavailable_count, cancelled_count = selected_rows(
        frame, scores, threshold, latency
    )
    routed = route(potential, latency)
    exclusions = winner_exclusions(routed, latency)
    rerouted = route(potential, latency, exclusions)
    return {
        "score_threshold": threshold,
        "selected_event_count": int((scores >= threshold).sum()),
        "base_metrics": metrics(
            routed, latency, stage_dates, unavailable_count, cancelled_count
        ),
        "winner_removed_event_ids": sorted(exclusions),
        "winner_removed_metrics": metrics(
            rerouted, latency, stage_dates, unavailable_count, cancelled_count
        ),
    }


def gate(result: dict[str, Any], stage: str) -> dict[str, bool]:
    base = result["base_metrics"]
    removed = result["winner_removed_metrics"]
    checks = {
        "minimum_20_trades": base["trade_count"] >= 20,
        "positive_mean": base["mean_net_bps"] is not None and base["mean_net_bps"] > 0,
        "positive_median": base["median_net_bps"] is not None and base["median_net_bps"] > 0,
        "positive_winner_removed_return": removed["total_return"] > 0,
        "positive_date_fraction_at_least_half": base["positive_date_fraction"] >= 0.5,
        "zero_unavailable_selected": base["selected_unavailable_count"] == 0,
    }
    if stage == "CALIBRATION":
        checks["top_five_share_at_most_0_5"] = base["top_five_positive_pnl_share"] <= 0.5
    else:
        checks["top_five_share_at_most_0_4"] = base["top_five_positive_pnl_share"] <= 0.4
        checks["winner_removed_growth_at_least_1pct_per_sample_day"] = (
            removed["geometric_growth_per_sample_day"] >= 0.01
        )
    return checks


def calibrate(input_dir: Path, output: Path) -> dict[str, Any]:
    frame = read_matrices(input_dir)
    observed_stages = sorted(frame["stage"].unique().tolist())
    if observed_stages != ["CALIBRATION", "FIT"]:
        raise RuntimeError(f"calibration job opened unexpected stages: {observed_stages}")
    fit = frame.loc[frame["stage"] == "FIT"].copy()
    calibration = frame.loc[frame["stage"] == "CALIBRATION"].copy()
    models, fit_diagnostics = fit_models(fit)
    pair_results: list[dict[str, Any]] = []
    thresholds: dict[str, dict[str, float]] = {}
    score_cache: dict[tuple[str, int], np.ndarray] = {}
    for name in MODEL_NAMES:
        thresholds[name] = {}
        if not all(latency in models[name] for latency in LATENCIES):
            continue
        for latency in LATENCIES:
            score_cache[(name, latency)] = predict_scores(models[name][latency], calibration)
        for quantile in QUANTILES:
            latency_results: dict[str, Any] = {}
            all_checks: dict[str, bool] = {}
            for latency in LATENCIES:
                scores = score_cache[(name, latency)]
                finite = scores[np.isfinite(scores)]
                if not len(finite):
                    threshold = math.inf
                else:
                    threshold = float(np.quantile(finite, quantile))
                thresholds[name][f"q{quantile:.3f}_l{latency}"] = threshold
                result = evaluate(
                    calibration,
                    scores,
                    threshold,
                    latency,
                    sorted(CALIBRATION_DATES),
                )
                checks = gate(result, "CALIBRATION")
                result["gate_checks"] = checks
                result["gate_passed"] = all(checks.values())
                latency_results[str(latency)] = result
                all_checks.update({f"l{latency}_{key}": value for key, value in checks.items()})
            passed = all(all_checks.values())
            objective = min(
                latency_results[str(latency)]["winner_removed_metrics"]["geometric_growth_per_sample_day"]
                for latency in LATENCIES
            )
            pair_results.append(
                {
                    "model_name": name,
                    "score_quantile": quantile,
                    "pair_gate_passed": passed,
                    "pair_objective_worst_latency_removed_growth": objective,
                    "latencies": latency_results,
                    "pair_gate_checks": all_checks,
                }
            )
    survivors = [result for result in pair_results if result["pair_gate_passed"]]
    survivors.sort(
        key=lambda result: (
            result["pair_objective_worst_latency_removed_growth"],
            min(
                result["latencies"][str(latency)]["base_metrics"]["trade_count"]
                for latency in LATENCIES
            ),
        ),
        reverse=True,
    )
    selected = survivors[0] if survivors else None
    freeze = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "calibration_survivor": selected is not None,
        "model_name": selected["model_name"] if selected else None,
        "score_quantile": selected["score_quantile"] if selected else None,
        "thresholds": (
            {
                str(latency): selected["latencies"][str(latency)]["score_threshold"]
                for latency in LATENCIES
            }
            if selected
            else {}
        ),
        "model_and_threshold_frozen_before_development": selected is not None,
        "official_2024_2026_opened": False,
    }
    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "stage": "CALIBRATION",
        "status": "CALIBRATION_SURVIVOR" if selected else "CALIBRATION_BELOW_GATE",
        "fit_rows": int(len(fit)),
        "calibration_rows": int(len(calibration)),
        "fit_diagnostics": fit_diagnostics,
        "pair_candidate_count": len(pair_results),
        "pair_survivor_count": len(survivors),
        "selected_pair": selected,
        "all_pair_results": pair_results,
        "freeze": freeze,
        "development_opened": False,
        "selection_evidence_opened": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump(models, output / "MODEL_BUNDLE.joblib", compress=3)
    (output / "FREEZE.json").write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n")
    (output / "CALIBRATION_RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def evaluate_frozen(
    input_dir: Path,
    model_bundle_path: Path,
    freeze_path: Path,
    stage: str,
    output: Path,
) -> dict[str, Any]:
    if stage not in {"DEVELOPMENT", "SELECTION_EVIDENCE"}:
        raise ValueError(stage)
    frame = read_matrices(input_dir)
    observed_stages = sorted(frame["stage"].unique().tolist())
    if observed_stages != [stage]:
        raise RuntimeError(f"{stage} job opened unexpected stages: {observed_stages}")
    freeze = json.loads(freeze_path.read_text())
    if freeze["calibration_survivor"] is not True:
        raise RuntimeError("attempted later stage without calibration survivor")
    models = joblib.load(model_bundle_path)
    name = str(freeze["model_name"])
    stage_dates = sorted(frame["date"].unique().tolist())
    latency_results: dict[str, Any] = {}
    all_checks: dict[str, bool] = {}
    for latency in LATENCIES:
        model = models[name][latency]
        scores = predict_scores(model, frame)
        threshold = float(freeze["thresholds"][str(latency)])
        result = evaluate(frame, scores, threshold, latency, stage_dates)
        checks = gate(result, stage)
        result["gate_checks"] = checks
        result["gate_passed"] = all(checks.values())
        latency_results[str(latency)] = result
        all_checks.update({f"l{latency}_{key}": value for key, value in checks.items()})
    passed = all(all_checks.values())
    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "stage": stage,
        "status": f"{stage}_SURVIVOR" if passed else f"{stage}_BELOW_GATE",
        "stage_gate_passed": passed,
        "frozen_model_name": name,
        "frozen_score_quantile": freeze["score_quantile"],
        "frozen_thresholds": freeze["thresholds"],
        "date_count": len(stage_dates),
        "dates": stage_dates,
        "matrix_rows": int(len(frame)),
        "latencies": latency_results,
        "pair_gate_checks": all_checks,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{stage}_RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def finalize(
    calibration_path: Path,
    development_path: Path | None,
    selection_path: Path | None,
    output: Path,
) -> dict[str, Any]:
    calibration = json.loads(calibration_path.read_text())
    development = json.loads(development_path.read_text()) if development_path and development_path.exists() else None
    selection = json.loads(selection_path.read_text()) if selection_path and selection_path.exists() else None
    if calibration["status"] == "CALIBRATION_BELOW_GATE":
        status = "CALIBRATION_BELOW_GATE"
        economic = "NO_CALIBRATION_PAIR_SURVIVED_BOTH_LATENCIES"
    elif development is None or development["stage_gate_passed"] is not True:
        status = "DEVELOPMENT_BELOW_GATE"
        economic = "CALIBRATION_SELECTED_PAIR_FAILED_SEQUENTIAL_DEVELOPMENT"
    elif selection is None or selection["stage_gate_passed"] is not True:
        status = "SELECTION_EVIDENCE_BELOW_GATE"
        economic = "DEVELOPMENT_SURVIVOR_FAILED_FIXED_POST_SELECTION_EVIDENCE"
    else:
        status = "PRE2024_SELECTION_SURVIVOR"
        economic = "EXPLAINABLE_ML_META_LABEL_SURVIVED_PRE2024_STAGES"
    result = {
        "schema_version": 1,
        "result_id": RESULT_ID,
        "claim_id": CLAIM_ID,
        "status": status,
        "hard_validity": "PASS",
        "economic_status": economic,
        "ranking_role": "NOT_RANK_ELIGIBLE_PRE2024_ML_SCREEN",
        "calibration": calibration,
        "development": development,
        "selection_evidence": selection,
        "pre2024_survivor": status == "PRE2024_SELECTION_SURVIVOR",
        "official_2024_opened": False,
        "official_2025_opened": False,
        "official_2026_opened": False,
        "orders_submitted": False,
        "paper_or_live_enabled": False,
        "next_action": (
            "Freeze the surviving model and reconstruct all remaining pre-2024 Bybit BBO/depth, funding, capacity and continuous marked NAV."
            if status == "PRE2024_SELECTION_SURVIVOR"
            else "Retire the BTC-to-alt overreaction-reclaim information unit without adjacent threshold or model expansion."
        ),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    summary = [
        "# Explainable SMT reclaim ML result",
        "",
        f"- status: `{status}`",
        f"- hard validity: `{result['hard_validity']}`",
        f"- pre-2024 survivor: `{result['pre2024_survivor']}`",
        f"- calibration pair survivors: `{calibration['pair_survivor_count']}`",
        f"- development opened: `{development is not None}`",
        f"- selection evidence opened: `{selection is not None}`",
        "",
        "No official 2024-2026 data or order path was opened.",
    ]
    (output / "SUMMARY.md").write_text("\n".join(summary) + "\n")
    return result


def self_test() -> None:
    assert len(FEATURE_COLUMNS) == 20
    assert len(MODEL_NAMES) == 2
    assert len(QUANTILES) == 3
    sample = pd.DataFrame(
        {
            "date": ["2022-01-09", "2022-01-09"],
            "event_id": ["a", "b"],
            "confirmation_time": [1.0, 2.0],
            "symbol": ["SOLUSDT", "XRPUSDT"],
            "horizon_seconds": [1, 1],
            "initial_residual_gap_bps": [20.0, 20.0],
            "btc_displacement_z": [4.0, 4.0],
            "model_score": [0.9, 0.8],
            "l100_entry_time": [1.1, 1.2],
            "l100_exit_time": [2.0, 1.8],
            "l100_gross_bps": [40.0, -10.0],
        }
    )
    routed = route(sample, 100)
    assert routed["event_id"].tolist() == ["a"]
    print("SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    calibration_parser = subparsers.add_parser("calibrate")
    calibration_parser.add_argument("--input", type=Path, required=True)
    calibration_parser.add_argument("--output", type=Path, required=True)

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--input", type=Path, required=True)
    evaluate_parser.add_argument("--model-bundle", type=Path, required=True)
    evaluate_parser.add_argument("--freeze", type=Path, required=True)
    evaluate_parser.add_argument("--stage", choices=["DEVELOPMENT", "SELECTION_EVIDENCE"], required=True)
    evaluate_parser.add_argument("--output", type=Path, required=True)

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--calibration", type=Path, required=True)
    finalize_parser.add_argument("--development", type=Path)
    finalize_parser.add_argument("--selection", type=Path)
    finalize_parser.add_argument("--output", type=Path, required=True)

    subparsers.add_parser("self-test")
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "calibrate":
        result = calibrate(args.input, args.output)
    elif args.command == "evaluate":
        result = evaluate_frozen(
            args.input,
            args.model_bundle,
            args.freeze,
            args.stage,
            args.output,
        )
    else:
        result = finalize(
            args.calibration,
            args.development,
            args.selection,
            args.output,
        )
    print(stable_json(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
