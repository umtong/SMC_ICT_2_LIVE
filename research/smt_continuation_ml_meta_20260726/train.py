from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

CLAIM_ID = "CLM-20260726-1906-SMT-CONTINUATION-ML-001"
RESULT_ID = "RES-20260726-SMT-CONTINUATION-ML-001"
COST_BPS = 24.0
LATENCIES = (100, 300)
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
    "pullback_depth_ratio",
    "milliseconds_event_to_pullback",
    "reacceleration_flow_strength_1s",
    "reacceleration_trade_count_1s",
    "target_realized_volatility_10s",
    "other_follower_residual_bps",
    "leader_move_at_entry_bps",
    "symbol_is_xrp",
)
BASELINE_COLUMNS = (
    "initial_residual_gap_bps",
    "pullback_depth_ratio",
    "leader_move_at_entry_bps",
    "target_realized_volatility_10s",
)
STAGES_2022 = ("FIT", "SCORE_CALIBRATION", "FIT_CONFIRMATION")


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def read_matrices(root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(root.rglob("matrix_*.csv.gz")):
        try:
            frame = pd.read_csv(path, compression="gzip")
        except pd.errors.EmptyDataError:
            continue
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise RuntimeError(f"no nonempty matrix files under {root}")
    frame = pd.concat(frames, ignore_index=True)
    frame["date"] = frame["date"].astype(str)
    frame["stage"] = frame["stage"].astype(str)
    frame["symbol_is_xrp"] = pd.to_numeric(frame["symbol_is_xrp"], errors="coerce")
    frame["signal_time"] = pd.to_numeric(frame["signal_time"], errors="coerce")
    return frame.sort_values(["signal_time", "symbol", "event_id"], kind="stable").reset_index(drop=True)


def features(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise RuntimeError(f"missing feature columns: {missing}")
    return frame.loc[:, columns].apply(pd.to_numeric, errors="coerce")


def label_mask(frame: pd.DataFrame) -> pd.Series:
    available = frame["label_available"].astype(str).str.lower().isin({"true", "1"})
    label = pd.to_numeric(frame["continuation_label"], errors="coerce")
    return available & label.isin([0, 1])


def make_logistic() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("classifier", LogisticRegression(
            C=0.25,
            penalty="l2",
            solver="lbfgs",
            class_weight="balanced",
            max_iter=2000,
            random_state=20260726,
        )),
    ])


def fit_model(frame: pd.DataFrame, columns: tuple[str, ...]) -> Pipeline:
    mask = label_mask(frame)
    x = features(frame.loc[mask], columns)
    y = pd.to_numeric(frame.loc[mask, "continuation_label"], errors="raise").astype(int)
    if len(y) < 40 or sorted(y.unique().tolist()) != [0, 1]:
        raise RuntimeError(f"insufficient two-class fit labels: rows={len(y)} classes={sorted(y.unique().tolist())}")
    model = make_logistic()
    model.fit(x, y)
    return model


def raw_scores(model: Pipeline, frame: pd.DataFrame, columns: tuple[str, ...]) -> np.ndarray:
    return np.asarray(model.predict_proba(features(frame, columns))[:, 1], dtype=np.float64)


def fit_isotonic(raw: np.ndarray, labels: np.ndarray) -> IsotonicRegression:
    finite = np.isfinite(raw) & np.isfinite(labels)
    x = raw[finite]
    y = labels[finite].astype(int)
    if len(y) < 20 or len(np.unique(y)) != 2:
        raise RuntimeError(f"insufficient isotonic labels: rows={len(y)} classes={np.unique(y).tolist()}")
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(x, y)
    return calibrator


def calibrated_scores(model: Pipeline, calibrator: IsotonicRegression, frame: pd.DataFrame, columns: tuple[str, ...]) -> np.ndarray:
    return np.asarray(calibrator.predict(raw_scores(model, frame, columns)), dtype=np.float64)


def diagnostic(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    finite = np.isfinite(labels) & np.isfinite(probabilities)
    y = labels[finite].astype(int)
    p = probabilities[finite]
    two = len(np.unique(y)) == 2
    return {
        "rows": int(len(y)),
        "positive_labels": int(y.sum()),
        "negative_labels": int((1 - y).sum()),
        "roc_auc": float(roc_auc_score(y, p)) if two else None,
        "brier_score": float(brier_score_loss(y, p)) if len(y) else None,
        "mean_probability": float(p.mean()) if len(p) else None,
    }


def expected_value_bps(frame: pd.DataFrame, probability: np.ndarray) -> np.ndarray:
    gap = pd.to_numeric(frame["initial_residual_gap_bps"], errors="coerce").to_numpy(float)
    ratio = pd.to_numeric(frame["pullback_depth_ratio"], errors="coerce").to_numpy(float)
    target = np.maximum(0.0, (1.50 - ratio) * gap)
    stop = np.maximum(6.0, (ratio - 0.25) * gap)
    return probability * target - (1.0 - probability) * stop - COST_BPS


def selected_frame(frame: pd.DataFrame, full_p: np.ndarray, baseline_p: np.ndarray) -> pd.DataFrame:
    work = frame.copy()
    work["model_probability"] = full_p
    work["baseline_probability"] = baseline_p
    work["probability_lift"] = full_p - baseline_p
    work["expected_value_bps"] = expected_value_bps(work, full_p)
    selected = work.loc[
        np.isfinite(work["model_probability"])
        & np.isfinite(work["baseline_probability"])
        & (work["probability_lift"] >= 0.05)
        & (work["expected_value_bps"] > 0.0)
    ].copy()
    return selected


def route(frame: pd.DataFrame, latency: int, excluded: set[str] | None = None) -> pd.DataFrame:
    excluded_ids = excluded or set()
    work = frame.loc[~frame["event_id"].astype(str).isin(excluded_ids)].copy()
    trade = work[f"l{latency}_trade"].astype(str).str.lower().isin({"true", "1"})
    unavailable = work[f"l{latency}_unavailable"].astype(str).str.lower().isin({"true", "1"})
    work = work.loc[trade & ~unavailable].copy()
    for column in (f"l{latency}_entry_time", f"l{latency}_exit_time", f"l{latency}_gross_bps"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=[f"l{latency}_entry_time", f"l{latency}_exit_time", f"l{latency}_gross_bps"])
    accepted: list[int] = []
    for stage_date in sorted(work["date"].unique().tolist()):
        day = work.loc[work["date"] == stage_date].sort_values(
            [f"l{latency}_entry_time", "model_probability", "expected_value_bps", "initial_residual_gap_bps", "symbol", "event_id"],
            ascending=[True, False, False, False, True, True],
            kind="stable",
        )
        free = -math.inf
        for idx, row in day.iterrows():
            entry = float(row[f"l{latency}_entry_time"])
            if entry <= free:
                continue
            accepted.append(idx)
            free = float(row[f"l{latency}_exit_time"])
    if not accepted:
        return work.iloc[0:0].copy()
    return work.loc[accepted].sort_values([f"l{latency}_entry_time", "event_id"], kind="stable").reset_index(drop=True)


def stop_bps(row: pd.Series) -> float:
    # The frozen parent executor charges the larger of a 50%-of-initial-gap
    # adverse move and 6 bp when the structural stop or source boundary is hit.
    gap = float(row["initial_residual_gap_bps"])
    return max(6.0, 0.50 * gap)


def account_return(row: pd.Series, latency: int, nav_usdt: float) -> tuple[float, float, float]:
    loss_per_notional = (stop_bps(row) + COST_BPS) / 10_000.0
    risk_leverage = 0.01 / loss_per_notional if loss_per_notional > 0 else 0.0
    prior_notional = float(pd.to_numeric(pd.Series([row.get("prior_quote_notional_3s")]), errors="coerce").iloc[0])
    participation_notional = 0.001 * prior_notional if np.isfinite(prior_notional) and prior_notional > 0 else 0.0
    participation_leverage = participation_notional / nav_usdt if nav_usdt > 0 else 0.0
    leverage = max(0.0, min(3.0, risk_leverage, participation_leverage))
    net = float(row[f"l{latency}_gross_bps"]) - COST_BPS
    account = max(-0.999999, leverage * net / 10_000.0)
    pnl_usdt = nav_usdt * account
    return account, leverage, pnl_usdt


def replay_account(routed: pd.DataFrame, latency: int) -> dict[str, Any]:
    nav_usdt = 10_000.0
    peak_usdt = nav_usdt
    rows: list[dict[str, Any]] = []
    for _, row in routed.iterrows():
        before = nav_usdt
        account, leverage, pnl_usdt = account_return(row, latency, before)
        nav_usdt = max(0.0, before + pnl_usdt)
        peak_usdt = max(peak_usdt, nav_usdt)
        rows.append({
            "event_id": str(row["event_id"]),
            "date": str(row["date"]),
            "account_return": account,
            "leverage": leverage,
            "pnl_usdt": pnl_usdt,
            "nav_before_usdt": before,
            "nav_after_usdt": nav_usdt,
            "drawdown": 1.0 - nav_usdt / peak_usdt if peak_usdt > 0 else 1.0,
        })
    return {"rows": rows, "ending_nav_usdt": nav_usdt}


def winner_exclusions(routed: pd.DataFrame, latency: int) -> set[str]:
    replay = replay_account(routed, latency)
    positives = [
        (float(item["pnl_usdt"]), str(item["event_id"]))
        for item in replay["rows"] if float(item["pnl_usdt"]) > 0
    ]
    positives.sort(reverse=True)
    count = int(math.ceil(0.10 * len(positives))) if positives else 0
    return {event_id for _, event_id in positives[:count]}


def path_metrics(
    selected: pd.DataFrame,
    routed: pd.DataFrame,
    latency: int,
    stage_dates: list[str],
) -> dict[str, Any]:
    replay = replay_account(routed, latency)
    replay_rows = replay["rows"]
    nav = replay["ending_nav_usdt"] / 10_000.0
    net_values = [float(row[f"l{latency}_gross_bps"]) - COST_BPS for _, row in routed.iterrows()]
    leverages = [float(item["leverage"]) for item in replay_rows]
    pnl_values = np.asarray([float(item["pnl_usdt"]) for item in replay_rows], dtype=float)
    account_values = np.asarray([float(item["account_return"]) for item in replay_rows], dtype=float)
    net = np.asarray(net_values, dtype=float)
    positive_pnl = pnl_values[pnl_values > 0]
    negative_pnl = pnl_values[pnl_values < 0]
    positive_bps = net[net > 0]
    negative_bps = net[net < 0]
    date_factor = {value: 1.0 for value in stage_dates}
    for item in replay_rows:
        date_factor[str(item["date"])] *= 1.0 + float(item["account_return"])
    selected_trade = selected[f"l{latency}_trade"].astype(str).str.lower().isin({"true", "1"})
    selected_unavailable = selected[f"l{latency}_unavailable"].astype(str).str.lower().isin({"true", "1"})
    selected_unavailable_count = int((selected_unavailable | ~selected_trade).sum())
    top_five_share = (
        float(np.sort(positive_pnl)[-5:].sum() / positive_pnl.sum())
        if len(positive_pnl) and positive_pnl.sum() > 0 else 1.0
    )
    span = (date_type.fromisoformat(max(stage_dates)) - date_type.fromisoformat(min(stage_dates))).days + 1
    maximum_drawdown = max([float(item["drawdown"]) for item in replay_rows], default=0.0)
    capacity_zero_count = int(sum(float(item["leverage"]) <= 0 for item in replay_rows))
    return {
        "selected_event_count": int(len(selected)),
        "trade_count": int(len(routed)),
        "selected_unavailable_or_no_fill_count": selected_unavailable_count,
        "zero_capacity_trade_count": capacity_zero_count,
        "mean_net_bps": float(net.mean()) if len(net) else None,
        "median_net_bps": float(np.median(net)) if len(net) else None,
        "profit_factor_net_bps": (
            float(positive_bps.sum() / -negative_bps.sum()) if len(negative_bps)
            else (999.0 if len(positive_bps) else 0.0)
        ),
        "profit_factor_account_usdt": (
            float(positive_pnl.sum() / -negative_pnl.sum()) if len(negative_pnl)
            else (999.0 if len(positive_pnl) else 0.0)
        ),
        "total_return": nav - 1.0,
        "ending_nav_usdt": replay["ending_nav_usdt"],
        "geometric_growth_per_sample_day": nav ** (1.0 / len(stage_dates)) - 1.0 if nav > 0 else -1.0,
        "geometric_growth_per_calendar_span_day": nav ** (1.0 / span) - 1.0 if nav > 0 else -1.0,
        "maximum_drawdown": maximum_drawdown,
        "positive_dates": int(sum(value > 1.0 for value in date_factor.values())),
        "positive_date_fraction": float(sum(value > 1.0 for value in date_factor.values()) / len(stage_dates)),
        "date_returns": {key: value - 1.0 for key, value in date_factor.items()},
        "top_five_positive_pnl_share": top_five_share,
        "median_leverage": float(np.median(leverages)) if leverages else 0.0,
        "maximum_leverage": float(np.max(leverages)) if leverages else 0.0,
        "account_replay": replay_rows,
    }


def evaluate_stage(frame: pd.DataFrame, full_p: np.ndarray, baseline_p: np.ndarray, stage_dates: list[str]) -> dict[str, Any]:
    selected = selected_frame(frame, full_p, baseline_p)
    latency_results: dict[str, Any] = {}
    for latency in LATENCIES:
        routed = route(selected, latency)
        excluded = winner_exclusions(routed, latency)
        rerouted = route(selected, latency, excluded)
        latency_results[str(latency)] = {
            "base_metrics": path_metrics(selected, routed, latency, stage_dates),
            "winner_removed_event_ids": sorted(excluded),
            "winner_removed_metrics": path_metrics(
                selected.loc[~selected["event_id"].astype(str).isin(excluded)],
                rerouted,
                latency,
                stage_dates,
            ),
            "ledger": routed.to_dict(orient="records"),
            "winner_removed_ledger": rerouted.to_dict(orient="records"),
        }
    return {
        "stage_dates": stage_dates,
        "matrix_rows": int(len(frame)),
        "label_rows": int(label_mask(frame).sum()),
        "selected_event_count": int(len(selected)),
        "latencies": latency_results,
    }


def economic_gate(stage_result: dict[str, Any], stage: str) -> dict[str, bool]:
    minimum_trades = 20 if stage == "FIT_CONFIRMATION" else 30
    minimum_positive_dates = 3 if stage == "FIT_CONFIRMATION" else 18
    checks: dict[str, bool] = {}
    for latency in LATENCIES:
        base = stage_result["latencies"][str(latency)]["base_metrics"]
        removed = stage_result["latencies"][str(latency)]["winner_removed_metrics"]
        prefix = f"l{latency}_"
        checks[prefix + "minimum_trades"] = base["trade_count"] >= minimum_trades
        checks[prefix + "positive_mean"] = base["mean_net_bps"] is not None and base["mean_net_bps"] > 0
        checks[prefix + "positive_median"] = base["median_net_bps"] is not None and base["median_net_bps"] > 0
        checks[prefix + "positive_profit_factor"] = base["profit_factor_net_bps"] > 1.0
        checks[prefix + "positive_capacity"] = base["zero_capacity_trade_count"] == 0
        checks[prefix + "positive_winner_removed_return"] = removed["total_return"] > 0
        checks[prefix + "winner_removed_growth_at_least_1pct_sample_day"] = removed["geometric_growth_per_sample_day"] >= 0.01
        checks[prefix + "positive_date_count"] = base["positive_dates"] >= minimum_positive_dates
        checks[prefix + "top_five_share"] = base["top_five_positive_pnl_share"] <= 0.40
        checks[prefix + "zero_unavailable_or_no_fill_selected"] = base["selected_unavailable_or_no_fill_count"] == 0
    return checks


def train(input_dir: Path, output: Path) -> dict[str, Any]:
    frame = read_matrices(input_dir)
    observed = sorted(frame["stage"].unique().tolist())
    if observed != sorted(STAGES_2022):
        raise RuntimeError(f"unexpected stages in 2022 train job: {observed}")
    fit = frame.loc[frame["stage"] == "FIT"].copy()
    calibration = frame.loc[frame["stage"] == "SCORE_CALIBRATION"].copy()
    confirmation = frame.loc[frame["stage"] == "FIT_CONFIRMATION"].copy()
    fit_rows = fit.loc[label_mask(fit)].copy()
    calibration_rows = calibration.loc[label_mask(calibration)].copy()
    confirmation_rows = confirmation.loc[label_mask(confirmation)].copy()

    early_gate = {
        "fit_label_rows_at_least_80": len(fit_rows) >= 80,
        "score_calibration_label_rows_at_least_40": len(calibration_rows) >= 40,
        "fit_confirmation_label_rows_at_least_40": len(confirmation_rows) >= 40,
        "fit_two_classes": sorted(pd.to_numeric(fit_rows["continuation_label"], errors="coerce").dropna().astype(int).unique().tolist()) == [0, 1],
        "calibration_two_classes": sorted(pd.to_numeric(calibration_rows["continuation_label"], errors="coerce").dropna().astype(int).unique().tolist()) == [0, 1],
        "confirmation_two_classes": sorted(pd.to_numeric(confirmation_rows["continuation_label"], errors="coerce").dropna().astype(int).unique().tolist()) == [0, 1],
    }
    output.mkdir(parents=True, exist_ok=True)
    if not all(early_gate.values()):
        result = {
            "schema_version": 1,
            "result_id": RESULT_ID,
            "claim_id": CLAIM_ID,
            "status": "FIT_SAMPLE_BELOW_GATE",
            "hard_validity": "PASS_PRE_MODEL_SAMPLE_GATE",
            "economic_status": "INSUFFICIENT_CAUSAL_TWO_CLASS_SAMPLE",
            "early_gate": early_gate,
            "fit_rows": int(len(fit_rows)),
            "score_calibration_rows": int(len(calibration_rows)),
            "fit_confirmation_rows": int(len(confirmation_rows)),
            "development_opened": False,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        }
        (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        (output / "FREEZE.json").write_text(json.dumps({"confirmation_survivor": False}, indent=2) + "\n")
        print("CONFIRMATION_SURVIVOR=false")
        return result

    full_model = fit_model(fit, FEATURE_COLUMNS)
    baseline_model = fit_model(fit, BASELINE_COLUMNS)
    cal_mask = label_mask(calibration)
    cal_labels = pd.to_numeric(calibration.loc[cal_mask, "continuation_label"], errors="raise").to_numpy(int)
    full_calibrator = fit_isotonic(raw_scores(full_model, calibration.loc[cal_mask], FEATURE_COLUMNS), cal_labels)
    baseline_calibrator = fit_isotonic(raw_scores(baseline_model, calibration.loc[cal_mask], BASELINE_COLUMNS), cal_labels)

    conf_mask = label_mask(confirmation)
    conf_labels = pd.to_numeric(confirmation.loc[conf_mask, "continuation_label"], errors="raise").to_numpy(int)
    full_conf_p = calibrated_scores(full_model, full_calibrator, confirmation.loc[conf_mask], FEATURE_COLUMNS)
    baseline_conf_p = calibrated_scores(baseline_model, baseline_calibrator, confirmation.loc[conf_mask], BASELINE_COLUMNS)
    full_diag = diagnostic(conf_labels, full_conf_p)
    baseline_diag = diagnostic(conf_labels, baseline_conf_p)
    prediction_gate = {
        "fit_confirmation_auc_at_least_0_55": full_diag["roc_auc"] is not None and full_diag["roc_auc"] >= 0.55,
        "auc_lift_at_least_0_01": full_diag["roc_auc"] is not None and baseline_diag["roc_auc"] is not None and full_diag["roc_auc"] - baseline_diag["roc_auc"] >= 0.01,
        "positive_brier_skill": full_diag["brier_score"] is not None and baseline_diag["brier_score"] is not None and full_diag["brier_score"] < baseline_diag["brier_score"],
    }

    full_all_p = calibrated_scores(full_model, full_calibrator, confirmation, FEATURE_COLUMNS)
    baseline_all_p = calibrated_scores(baseline_model, baseline_calibrator, confirmation, BASELINE_COLUMNS)
    confirmation_result = evaluate_stage(
        confirmation,
        full_all_p,
        baseline_all_p,
        sorted(confirmation["date"].unique().tolist()),
    )
    economic_checks = economic_gate(confirmation_result, "FIT_CONFIRMATION")
    survivor = all(early_gate.values()) and all(prediction_gate.values()) and all(economic_checks.values())

    bundle = {
        "full_model": full_model,
        "baseline_model": baseline_model,
        "full_calibrator": full_calibrator,
        "baseline_calibrator": baseline_calibrator,
        "feature_columns": FEATURE_COLUMNS,
        "baseline_columns": BASELINE_COLUMNS,
    }
    joblib.dump(bundle, output / "MODEL_BUNDLE.joblib", compress=3)
    freeze = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "confirmation_survivor": survivor,
        "model": "standardized_l2_logistic_C_0_25",
        "calibration": "isotonic_score_calibration_only",
        "probability_lift_required": 0.05,
        "expected_value_cost_bps": COST_BPS,
        "feature_columns": list(FEATURE_COLUMNS),
        "baseline_columns": list(BASELINE_COLUMNS),
        "model_and_route_frozen_before_development": True,
        "official_2024_2026_opened": False,
    }
    (output / "FREEZE.json").write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n")
    confirmation_serializable = json.loads(json.dumps(confirmation_result, default=str))
    for latency in LATENCIES:
        confirmation_serializable["latencies"][str(latency)].pop("ledger", None)
        confirmation_serializable["latencies"][str(latency)].pop("winner_removed_ledger", None)
        confirmation_serializable["latencies"][str(latency)]["base_metrics"].pop("account_replay", None)
        confirmation_serializable["latencies"][str(latency)]["winner_removed_metrics"].pop("account_replay", None)
    result = {
        "schema_version": 1,
        "result_id": RESULT_ID,
        "claim_id": CLAIM_ID,
        "status": "FIT_CONFIRMATION_SURVIVOR" if survivor else "FIT_CONFIRMATION_BELOW_GATE",
        "hard_validity": "PASS",
        "economic_status": "CONDITIONAL_DEVELOPMENT_REQUIRED" if survivor else "BELOW_GATE",
        "early_gate": early_gate,
        "prediction": {
            "full": full_diag,
            "baseline": baseline_diag,
            "auc_lift": (full_diag["roc_auc"] - baseline_diag["roc_auc"]) if full_diag["roc_auc"] is not None and baseline_diag["roc_auc"] is not None else None,
            "brier_skill": (baseline_diag["brier_score"] - full_diag["brier_score"]) / baseline_diag["brier_score"] if full_diag["brier_score"] is not None and baseline_diag["brier_score"] not in (None, 0) else None,
            "gate_checks": prediction_gate,
        },
        "fit_confirmation": confirmation_serializable,
        "economic_gate_checks": economic_checks,
        "development_opened": False,
        "official_2024_opened": False,
        "official_2025_opened": False,
        "official_2026_opened": False,
        "orders_submitted": False,
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"CONFIRMATION_SURVIVOR={'true' if survivor else 'false'}")
    return result


def evaluate_development(input_dir: Path, bundle_path: Path, freeze_path: Path, output: Path) -> dict[str, Any]:
    freeze = json.loads(freeze_path.read_text())
    if freeze.get("confirmation_survivor") is not True:
        raise RuntimeError("development opened without fit-confirmation survivor")
    frame = read_matrices(input_dir)
    if sorted(frame["stage"].unique().tolist()) != ["DEVELOPMENT"]:
        raise RuntimeError("development job opened non-development rows")
    bundle = joblib.load(bundle_path)
    full_p = calibrated_scores(bundle["full_model"], bundle["full_calibrator"], frame, tuple(bundle["feature_columns"]))
    baseline_p = calibrated_scores(bundle["baseline_model"], bundle["baseline_calibrator"], frame, tuple(bundle["baseline_columns"]))
    mask = label_mask(frame)
    labels = pd.to_numeric(frame.loc[mask, "continuation_label"], errors="raise").to_numpy(int)
    full_diag = diagnostic(labels, full_p[mask.to_numpy()])
    baseline_diag = diagnostic(labels, baseline_p[mask.to_numpy()])
    stage_result = evaluate_stage(frame, full_p, baseline_p, sorted(frame["date"].unique().tolist()))
    checks = economic_gate(stage_result, "DEVELOPMENT")
    prediction_checks = {
        "development_auc_at_least_0_55": full_diag["roc_auc"] is not None and full_diag["roc_auc"] >= 0.55,
        "development_auc_lift_nonnegative": full_diag["roc_auc"] is not None and baseline_diag["roc_auc"] is not None and full_diag["roc_auc"] >= baseline_diag["roc_auc"],
        "development_brier_not_worse": full_diag["brier_score"] is not None and baseline_diag["brier_score"] is not None and full_diag["brier_score"] <= baseline_diag["brier_score"],
    }
    passed = all(checks.values()) and all(prediction_checks.values())
    serializable = json.loads(json.dumps(stage_result, default=str))
    for latency in LATENCIES:
        serializable["latencies"][str(latency)].pop("ledger", None)
        serializable["latencies"][str(latency)].pop("winner_removed_ledger", None)
        serializable["latencies"][str(latency)]["base_metrics"].pop("account_replay", None)
        serializable["latencies"][str(latency)]["winner_removed_metrics"].pop("account_replay", None)
    result = {
        "schema_version": 1,
        "result_id": RESULT_ID,
        "claim_id": CLAIM_ID,
        "status": "PRE2024_DEVELOPMENT_SURVIVOR" if passed else "DEVELOPMENT_BELOW_GATE",
        "hard_validity": "PASS",
        "economic_status": "SURVIVOR_REQUIRES_EXACT_BBO_FULL_PRE2024" if passed else "BELOW_GATE",
        "prediction": {"full": full_diag, "baseline": baseline_diag, "gate_checks": prediction_checks},
        "development": serializable,
        "economic_gate_checks": checks,
        "pre2024_survivor": passed,
        "official_2024_opened": False,
        "official_2025_opened": False,
        "official_2026_opened": False,
        "orders_submitted": False,
        "next_action": (
            "Freeze the exact model and reconstruct all remaining pre-2024 Bybit BBO/depth, funding, capacity and continuous marked NAV before official 2024."
            if passed else
            "Retire the exact SMT overdelivery-pullback continuation meta-label without adjacent model, threshold, setup, risk or leverage tuning."
        ),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def self_test() -> None:
    sample = pd.DataFrame({
        "date": ["2022-10-02", "2022-10-02"],
        "event_id": ["a", "b"],
        "model_probability": [0.9, 0.8],
        "expected_value_bps": [10.0, 8.0],
        "initial_residual_gap_bps": [30.0, 30.0],
        "pullback_depth_ratio": [0.6, 0.6],
        "l100_trade": [True, True],
        "l100_unavailable": [False, False],
        "l100_entry_time": [1.0, 1.2],
        "l100_exit_time": [2.0, 1.8],
        "l100_gross_bps": [60.0, -20.0],
        "symbol": ["SOLUSDT", "XRPUSDT"],
    })
    routed = route(sample, 100)
    assert routed["event_id"].tolist() == ["a"]
    assert len(FEATURE_COLUMNS) == 18
    assert len(BASELINE_COLUMNS) == 4
    print("SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    train_parser = sub.add_parser("train")
    train_parser.add_argument("--input", type=Path, required=True)
    train_parser.add_argument("--output", type=Path, required=True)
    dev_parser = sub.add_parser("evaluate-development")
    dev_parser.add_argument("--input", type=Path, required=True)
    dev_parser.add_argument("--bundle", type=Path, required=True)
    dev_parser.add_argument("--freeze", type=Path, required=True)
    dev_parser.add_argument("--output", type=Path, required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "train":
        result = train(args.input, args.output)
    else:
        result = evaluate_development(args.input, args.bundle, args.freeze, args.output)
    print(stable_json(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
