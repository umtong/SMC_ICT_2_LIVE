from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

import train as engine

engine.FIT_DATES = {
    "2022-01-09", "2022-03-13", "2022-05-08", "2022-07-10", "2022-09-11", "2022-11-13"
}
engine.CALIBRATION_DATES = {
    "2022-02-13", "2022-04-10", "2022-06-12", "2022-08-14", "2022-10-09", "2022-12-11"
}
engine.DEVELOPMENT_DATES = {
    "2023-01-08", "2023-02-12", "2023-03-12", "2023-04-09",
    "2023-05-14", "2023-06-11", "2023-07-09", "2023-08-13"
}
engine.SELECTION_DATES = {
    "2023-09-24", "2023-10-22", "2023-11-26", "2023-12-31"
}


def corrected_read_matrices(root: Path) -> pd.DataFrame:
    paths = sorted(root.rglob("matrix_*.csv.gz"))
    if not paths:
        raise RuntimeError(f"no matrix files under {root}")
    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            frame = pd.read_csv(path, compression="gzip")
        except pd.errors.EmptyDataError:
            continue
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise RuntimeError("every causal MSS matrix is empty")
    frame = pd.concat(frames, ignore_index=True)
    frame["symbol_is_xrp"] = (frame["symbol"].astype(str) == "XRPUSDT").astype(float)
    frame["date"] = frame["date"].astype(str)
    frame["stage"] = frame["stage"].astype(str)
    return frame.sort_values(
        ["confirmation_time", "symbol", "horizon_seconds", "event_id"], kind="stable"
    ).reset_index(drop=True)


def corrected_evaluate_frozen(
    input_dir: Path,
    model_bundle_path: Path,
    freeze_path: Path,
    stage: str,
    output: Path,
) -> dict[str, Any]:
    if stage not in {"DEVELOPMENT", "SELECTION_EVIDENCE"}:
        raise ValueError(stage)
    frame = corrected_read_matrices(input_dir)
    observed_stages = sorted(frame["stage"].unique().tolist())
    if observed_stages != [stage]:
        raise RuntimeError(f"{stage} job opened unexpected stages: {observed_stages}")
    freeze = json.loads(freeze_path.read_text())
    if freeze["calibration_survivor"] is not True:
        raise RuntimeError("attempted later stage without calibration survivor")
    models = joblib.load(model_bundle_path)
    name = str(freeze["model_name"])
    stage_dates = (
        sorted(engine.DEVELOPMENT_DATES)
        if stage == "DEVELOPMENT"
        else sorted(engine.SELECTION_DATES)
    )
    latency_results: dict[str, Any] = {}
    all_checks: dict[str, bool] = {}
    for latency in engine.LATENCIES:
        model = models[name][latency]
        scores = engine.predict_scores(model, frame)
        threshold = float(freeze["thresholds"][str(latency)])
        result = engine.evaluate(frame, scores, threshold, latency, stage_dates)
        checks = engine.gate(result, stage)
        result["gate_checks"] = checks
        result["gate_passed"] = all(checks.values())
        latency_results[str(latency)] = result
        all_checks.update({f"l{latency}_{key}": value for key, value in checks.items()})
    passed = all(all_checks.values())
    result = {
        "schema_version": 1,
        "claim_id": engine.CLAIM_ID,
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
    (output / f"{stage}_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result


engine.read_matrices = corrected_read_matrices
engine.evaluate_frozen = corrected_evaluate_frozen


if __name__ == "__main__":
    raise SystemExit(engine.main())
