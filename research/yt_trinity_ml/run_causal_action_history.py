#!/usr/bin/env python3
"""Use 2021-2022 learning, 2023H1 calibration and 2023H2 selection.

No 2020 data is used. The complete order action, exit variant, score threshold,
risk fraction and leverage are fixed before 2024H1 is opened. This is a coarse
one-minute economic screen and has no ranking authority until event-tape replay.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from run_causal_action_fast import _rows_fast
from run_causal_action_v1 import (
    ScreenConfig,
    _account,
    _causal_risk_grid,
    _feature_columns,
    _jsonable,
)
from run_research import PRIMARY, load_canonical_frames, load_instrument_rules
from system.causal_action_candidates import generate_causal_action_candidates_by_symbol
from system.causal_action_history_model import ExplicitHistoryActionValueModel
from system.core import FeatureConfig


PRE2024_SEGMENTS = ("PRE_2024_2021", "PRE_2024_2022", "PRE_2024_2023")
EXIT_VARIANTS = (
    "FULL_STRUCTURAL",
    "CAP_2R",
    "TP1_50_BE_STRUCT",
    "PD_ARRAY_FAILURE",
)
BASE_START = pd.Timestamp("2021-01-01T00:00:00Z")
BASE_END = pd.Timestamp("2023-01-01T00:00:00Z")
CALIBRATION_START = BASE_END
CALIBRATION_END = pd.Timestamp("2023-07-01T00:00:00Z")
SELECTION_START = CALIBRATION_END
SELECTION_END = pd.Timestamp("2024-01-01T00:00:00Z")
EVALUATION_START = SELECTION_END
EVALUATION_END = pd.Timestamp("2024-07-01T00:00:00Z")


def _period(
    rows: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    require_resolved_before_end: bool = True,
) -> pd.DataFrame:
    selected = rows[
        (pd.to_datetime(rows["activation"], utc=True) >= start)
        & (pd.to_datetime(rows["activation"], utc=True) < end)
    ].copy()
    if require_resolved_before_end:
        selected = selected[
            pd.to_datetime(selected["event_end"], utc=True) < end
        ].copy()
    return selected


def _score(
    model: ExplicitHistoryActionValueModel,
    rows: pd.DataFrame,
) -> pd.DataFrame:
    predicted = model.predict(rows)
    if predicted.empty:
        return rows.iloc[0:0].copy()
    scored = rows.loc[predicted.index].copy()
    for name in predicted.columns:
        scored[name] = predicted.loc[scored.index, name]
    scored["score"] = scored["lower_confidence_net_r"]
    return scored


def _economics(rows: pd.DataFrame) -> dict[str, Any]:
    if rows.empty:
        return {"rows": 0}
    result: dict[str, Any] = {
        "rows": int(len(rows)),
        "filled": int(rows["filled"].astype(int).sum()),
        "fill_rate": float(rows["filled"].astype(int).mean()),
        "mean_budget_r": float(rows["net_budget_r"].astype(float).mean()),
        "median_budget_r": float(rows["net_budget_r"].astype(float).median()),
        "positive_rate": float(rows["net_budget_r"].astype(float).gt(0).mean()),
        "status_counts": {
            str(key): int(value)
            for key, value in rows["status"].astype(str).value_counts().items()
        },
    }
    result["by_action"] = {
        str(action): {
            "rows": int(len(group)),
            "filled": int(group["filled"].astype(int).sum()),
            "fill_rate": float(group["filled"].astype(int).mean()),
            "mean_budget_r": float(group["net_budget_r"].astype(float).mean()),
            "positive_rate": float(group["net_budget_r"].astype(float).gt(0).mean()),
            "status_counts": {
                str(key): int(value)
                for key, value in group["status"].astype(str).value_counts().items()
            },
        }
        for action, group in rows.groupby("action", sort=True)
    }
    return result


def _select_pre2024(
    rows: pd.DataFrame,
    feature_names: Sequence[str],
    rule_map: Mapping[str, tuple[float, float]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any]]:
    base = _period(rows, BASE_START, BASE_END)
    calibration = _period(rows, CALIBRATION_START, CALIBRATION_END)
    selection = _period(rows, SELECTION_START, SELECTION_END, require_resolved_before_end=False)
    raw: dict[str, Any] = {}
    attempts: list[dict[str, Any]] = []
    survivors: list[dict[str, Any]] = []

    for variant in EXIT_VARIANTS:
        base_variant = base[base["exit_variant"].astype(str).eq(variant)].copy()
        calibration_variant = calibration[
            calibration["exit_variant"].astype(str).eq(variant)
        ].copy()
        selection_variant = selection[
            selection["exit_variant"].astype(str).eq(variant)
        ].copy()
        raw[variant] = {
            "base_2021_2022": _economics(base_variant),
            "calibration_2023_h1": _economics(calibration_variant),
            "selection_2023_h2": _economics(selection_variant),
        }
        if len(base_variant) < 100 or len(calibration_variant) < 50 or len(selection_variant) < 50:
            continue
        try:
            model = ExplicitHistoryActionValueModel().fit(
                base_variant,
                calibration_variant,
                feature_names,
            )
        except ValueError as exc:
            raw[variant]["model_error"] = str(exc)
            continue
        scored = _score(model, selection_variant)
        if scored.empty:
            raw[variant]["model_error"] = "no action head scored 2023H2"
            continue

        for quantile in (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.925, 0.95, 0.975):
            raw_threshold = float(scored["score"].quantile(quantile))
            threshold = max(0.0, raw_threshold)
            basic = _account(
                scored,
                SELECTION_START,
                SELECTION_END,
                threshold,
                0.01,
                5.0,
                rule_map,
            )
            attempt = {
                "variant": variant,
                "quantile": quantile,
                "raw_threshold": raw_threshold,
                "threshold": threshold,
                "basic_account_2023_h2": basic,
                "model_fingerprint": model.fingerprint(),
                "model_diagnostics": model.diagnostics(),
            }
            attempts.append(attempt)
            if basic["filled_trades"] < 15 or basic["geometric_daily_growth"] <= 0:
                continue

            selected_rows = scored[scored["score"] >= threshold].copy()
            risk_grid, risk_domain = _causal_risk_grid(selected_rows)
            best_risk: tuple[tuple[float, float, float], float, float, dict[str, Any]] | None = None
            for risk_fraction in risk_grid:
                for maximum_leverage in (2.0, 5.0, 10.0, 20.0, 35.0, 50.0, 75.0, 100.0):
                    account = _account(
                        scored,
                        SELECTION_START,
                        SELECTION_END,
                        threshold,
                        float(risk_fraction),
                        maximum_leverage,
                        rule_map,
                    )
                    if account["ending_nav"] <= 0:
                        continue
                    key = (
                        float(account["geometric_daily_growth"]),
                        float(account["nav_multiple"]),
                        -float(account["maximum_drawdown_at_realized_events"]),
                    )
                    if best_risk is None or key > best_risk[0]:
                        best_risk = (key, float(risk_fraction), maximum_leverage, account)
            if best_risk is None:
                continue
            survivors.append(
                {
                    **attempt,
                    "risk_fraction": best_risk[1],
                    "maximum_leverage": best_risk[2],
                    "optimized_account_2023_h2": best_risk[3],
                    "risk_domain": risk_domain,
                }
            )

    attempts.sort(
        key=lambda row: (
            float(row["basic_account_2023_h2"]["geometric_daily_growth"]),
            float(row["basic_account_2023_h2"]["nav_multiple"]),
        ),
        reverse=True,
    )
    if not survivors:
        return None, attempts, raw
    selected = max(
        survivors,
        key=lambda row: (
            float(row["optimized_account_2023_h2"]["geometric_daily_growth"]),
            float(row["optimized_account_2023_h2"]["nav_multiple"]),
            -float(row["optimized_account_2023_h2"]["maximum_drawdown_at_realized_events"]),
        ),
    )
    return selected, attempts, raw


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    rules = load_instrument_rules(args.instrument_rules, PRIMARY)
    rule_map = {
        rule.symbol: (rule.quantity_step, rule.minimum_quantity)
        for rule in rules
    }
    screen = ScreenConfig()

    decision_pre, execution_pre, funding_pre = load_canonical_frames(
        args.data_root,
        args.repo_root,
        PRIMARY,
        PRE2024_SEGMENTS,
    )
    _, candidates_pre, diagnostics_pre = generate_causal_action_candidates_by_symbol(
        decision_pre,
        FeatureConfig(),
    )
    rows_pre = _rows_fast(
        candidates_pre,
        execution_pre,
        funding_pre,
        SELECTION_END,
        EXIT_VARIANTS,
        screen,
    )
    if rows_pre.empty:
        raise RuntimeError("no causal action rows across 2021-2023")
    rows_pre.to_parquet(args.output / "ACTION_LABELS_2021_2023.parquet", index=False)
    feature_names = _feature_columns(rows_pre)

    selected, attempts, raw = _select_pre2024(
        rows_pre,
        feature_names,
        rule_map,
    )
    base_summary = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "stage": "EXPLICIT_2021_2023_CAUSAL_ACTION_COARSE_NOT_RANKABLE",
        "model_contract": {
            "base_learning_start": BASE_START,
            "base_learning_end_exclusive": BASE_END,
            "calibration_start": CALIBRATION_START,
            "calibration_end_exclusive": CALIBRATION_END,
            "final_selection_start": SELECTION_START,
            "final_selection_end_exclusive": SELECTION_END,
            "official_evaluation_start": EVALUATION_START,
            "official_evaluation_end_exclusive": EVALUATION_END,
            "excluded_history": ["2020 and earlier"],
            "pre2024_segments": list(PRE2024_SEGMENTS),
        },
        "fixed_activation_latency_ms": screen.activation_latency_ms,
        "candidate_count_pre2024": len(candidates_pre),
        "action_rows_pre2024": len(rows_pre),
        "candidate_diagnostics_pre2024": diagnostics_pre,
        "feature_count": len(feature_names),
        "raw_pre2024": raw,
        "selection_attempts": attempts,
        "causal_armed_candidate_universe": True,
        "ranking_effect": "NONE_COARSE_1M_NOT_RANKABLE",
    }

    if selected is None:
        result = {
            **base_summary,
            "decision": "NO_POSITIVE_EXPLICIT_HISTORY_SURVIVOR",
            "official_2024_h1_opened": False,
            "target_exceeded_coarse": False,
        }
        path = args.output / "CAUSAL_ACTION_HISTORY_RESULT.json"
        path.write_text(
            json.dumps(_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (args.output / "CAUSAL_ACTION_HISTORY_RESULT.sha256").write_text(
            f"{sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
            encoding="utf-8",
        )
        print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    variant = str(selected["variant"])
    quantile = float(selected["quantile"])
    production_base = _period(
        rows_pre[rows_pre["exit_variant"].astype(str).eq(variant)].copy(),
        BASE_START,
        CALIBRATION_END,
    )
    production_calibration = _period(
        rows_pre[rows_pre["exit_variant"].astype(str).eq(variant)].copy(),
        SELECTION_START,
        SELECTION_END,
    )
    production_model = ExplicitHistoryActionValueModel().fit(
        production_base,
        production_calibration,
        feature_names,
    )
    scored_calibration = _score(production_model, production_calibration)
    frozen_threshold = max(
        0.0,
        float(scored_calibration["score"].quantile(quantile)),
    )

    # Rebuild the exact information state available at 2024-01-01. Loading the
    # evaluation shard alone would reset rolling indicators, prior-session liquidity
    # and still-valid SMC narrative states at the boundary. Pre-2024 rows warm the
    # causal state machine, but only actions whose activation is inside H1 may trade.
    evaluation_context_segments = (*PRE2024_SEGMENTS, "2024_H1")
    decision_context, execution_context, funding_context = load_canonical_frames(
        args.data_root,
        args.repo_root,
        PRIMARY,
        evaluation_context_segments,
    )
    _, candidates_context, diagnostics_context = generate_causal_action_candidates_by_symbol(
        decision_context,
        FeatureConfig(),
    )
    candidates_2024 = [
        candidate for candidate in candidates_context
        if EVALUATION_START <= pd.Timestamp(candidate.timestamp) < EVALUATION_END
    ]
    rows_2024 = _rows_fast(
        candidates_2024,
        execution_context,
        funding_context,
        EVALUATION_END,
        (variant,),
        screen,
    )
    diagnostics_2024 = {
        "context_segments": list(evaluation_context_segments),
        "full_context_candidate_count": len(candidates_context),
        "evaluation_candidate_count": len(candidates_2024),
        "by_symbol": diagnostics_context,
    }
    scored_2024 = _score(production_model, rows_2024)
    account_2024 = _account(
        scored_2024,
        EVALUATION_START,
        EVALUATION_END,
        frozen_threshold,
        float(selected["risk_fraction"]),
        float(selected["maximum_leverage"]),
        rule_map,
    )
    scored_2024.to_parquet(
        args.output / "SCORED_ACTIONS_2024_H1.parquet",
        index=False,
    )

    result = {
        **base_summary,
        "stage": "2024_H1_EXPLICIT_HISTORY_CAUSAL_ACTION_COARSE_NOT_RANKABLE",
        "selected_pre2024": selected,
        "production_refit_contract": {
            "base_start": BASE_START,
            "base_end_exclusive": CALIBRATION_END,
            "calibration_start": SELECTION_START,
            "calibration_end_exclusive": SELECTION_END,
            "variant": variant,
            "score_quantile": quantile,
            "frozen_threshold": frozen_threshold,
            "risk_fraction": float(selected["risk_fraction"]),
            "maximum_leverage": float(selected["maximum_leverage"]),
            "model_fingerprint": production_model.fingerprint(),
            "model_diagnostics": production_model.diagnostics(),
        },
        "candidate_count_2024_h1": len(candidates_2024),
        "action_rows_2024_h1": len(rows_2024),
        "scored_action_rows_2024_h1": len(scored_2024),
        "candidate_diagnostics_2024_h1": diagnostics_2024,
        "result_2024_h1": account_2024,
        "official_2024_h1_opened": True,
        "target_exceeded_coarse": account_2024["geometric_daily_growth"] >= 0.01,
        "decision": (
            "ADVANCE_EXACT_HISTORY_SURVIVOR_TO_EVENT_TAPE_AND_CONTINUOUS_EVALUATION"
            if account_2024["geometric_daily_growth"] > 0
            else "KEEP_UNIFIED_SMC_NARRATIVE_REPAIR_ACTION_GEOMETRY_OR_MODEL"
        ),
    }
    path = args.output / "CAUSAL_ACTION_HISTORY_RESULT.json"
    path.write_text(
        json.dumps(_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output / "CAUSAL_ACTION_HISTORY_RESULT.sha256").write_text(
        f"{sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
        encoding="utf-8",
    )
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True))
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
