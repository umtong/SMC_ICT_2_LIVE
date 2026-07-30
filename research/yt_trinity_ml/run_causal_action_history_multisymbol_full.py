#!/usr/bin/env python3
"""Continuously replay the frozen pre-2024 selected symbol set through 2026H1."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from run_causal_action_fast import _rows_fast
from run_causal_action_history import (
    BASE_START,
    CALIBRATION_END,
    PRE2024_SEGMENTS,
    SELECTION_END,
    SELECTION_START,
    _history_feature_columns,
    _period,
    _score,
)
from run_causal_action_history_full import (
    EVALUATION_END,
    EVALUATION_SEGMENTS,
    EVALUATION_START,
    _half_years,
)
from run_causal_action_v1 import ScreenConfig, _account, _jsonable
from run_research import load_canonical_frames, load_instrument_rules
from system.causal_action_candidates import generate_causal_action_candidates_by_symbol
from system.causal_action_history_model import ExplicitHistoryActionValueModel
from system.core import FeatureConfig


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    pointer = json.loads(args.pointer.read_text(encoding="utf-8"))
    result = pointer.get("result") or {}
    h1 = result.get("result_2024_h1") or {}
    if (
        pointer.get("job_status") != "success"
        or int(pointer.get("exit_code", 99)) != 0
        or float(h1.get("geometric_daily_growth", 0.0)) <= 0
    ):
        payload = {
            "schema_version": 1,
            "stage": "MULTISYMBOL_FULL_PERIOD_NOT_OPENED",
            "reason": "positive completed conditional-symbol 2024H1 result is absent",
            "ranking_effect": "NONE",
        }
        (args.output / "CAUSAL_ACTION_MULTISYMBOL_FULL_RESULT.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
        return 0

    symbols = tuple(str(value) for value in result["selected_symbols"])
    selected = result["selected_pre2024"]
    contract = result["production_refit_contract"]
    variant = str(contract["variant"])
    quantile = float(contract["score_quantile"])
    risk_fraction = float(contract["risk_fraction"])
    maximum_leverage = float(contract["maximum_leverage"])

    rules = load_instrument_rules(args.instrument_rules, symbols)
    rule_map = {
        rule.symbol: (rule.quantity_step, rule.minimum_quantity)
        for rule in rules
    }
    screen = ScreenConfig()

    decision_pre, execution_pre, funding_pre = load_canonical_frames(
        args.data_root,
        args.repo_root,
        symbols,
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
        (variant,),
        screen,
    )
    feature_names = _history_feature_columns(rows_pre)
    production_base = _period(rows_pre, BASE_START, CALIBRATION_END)
    production_calibration = _period(rows_pre, SELECTION_START, SELECTION_END)
    model = ExplicitHistoryActionValueModel().fit(
        production_base,
        production_calibration,
        feature_names,
    )
    scored_calibration = _score(model, production_calibration)
    frozen_threshold = max(0.0, float(scored_calibration["score"].quantile(quantile)))
    if not np.isclose(
        frozen_threshold,
        float(contract["frozen_threshold"]),
        rtol=1e-10,
        atol=1e-12,
    ):
        raise RuntimeError("conditional-symbol frozen threshold mismatch")
    if model.fingerprint() != contract["model_fingerprint"]:
        raise RuntimeError("conditional-symbol model fingerprint mismatch")

    decision_eval, execution_eval, funding_eval = load_canonical_frames(
        args.data_root,
        args.repo_root,
        symbols,
        EVALUATION_SEGMENTS,
    )
    _, candidates_eval, diagnostics_eval = generate_causal_action_candidates_by_symbol(
        decision_eval,
        FeatureConfig(),
    )
    rows_eval = _rows_fast(
        candidates_eval,
        execution_eval,
        funding_eval,
        EVALUATION_END,
        (variant,),
        screen,
    )
    scored_eval = _score(model, rows_eval)
    scored_eval.to_parquet(
        args.output / "MULTISYMBOL_SCORED_ACTIONS_2024_2026H1.parquet",
        index=False,
    )
    account = _account(
        scored_eval,
        EVALUATION_START,
        EVALUATION_END,
        frozen_threshold,
        risk_fraction,
        maximum_leverage,
        rule_map,
    )
    payload = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "stage": "MULTISYMBOL_2024_TO_2026H1_COARSE_NOT_RANKABLE",
        "evaluation_start": EVALUATION_START,
        "evaluation_end_exclusive": EVALUATION_END,
        "initial_nav": 10000.0,
        "continuous_nav_no_resets": True,
        "global_entry_slot": 1,
        "selected_symbols": list(symbols),
        "selected_pre2024": {
            "variant": variant,
            "score_quantile": quantile,
            "frozen_threshold": frozen_threshold,
            "risk_fraction": risk_fraction,
            "maximum_leverage": maximum_leverage,
            "model_fingerprint": model.fingerprint(),
            "model_diagnostics": model.diagnostics(),
        },
        "pre2024_candidate_count": len(candidates_pre),
        "pre2024_candidate_diagnostics": diagnostics_pre,
        "evaluation_candidate_count": len(candidates_eval),
        "evaluation_candidate_diagnostics": diagnostics_eval,
        "evaluation_action_rows": len(rows_eval),
        "evaluation_scored_rows": len(scored_eval),
        "continuous_account": account,
        "half_years": _half_years(account),
        "target_exceeded_coarse": account["geometric_daily_growth"] >= 0.01,
        "decision": (
            "ADVANCE_MULTISYMBOL_TO_EVENT_TAPE_AND_LIVE_IDENTICAL_ENGINE"
            if account["geometric_daily_growth"] >= 0.01
            else "KEEP_UNIFIED_SMC_NARRATIVE_CONTINUE_IMPLEMENTATION_REFINEMENT"
        ),
        "ranking_effect": "NONE_COARSE_1M_NOT_RANKABLE",
    }
    path = args.output / "CAUSAL_ACTION_MULTISYMBOL_FULL_RESULT.json"
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    (args.output / "CAUSAL_ACTION_MULTISYMBOL_FULL_RESULT.sha256").write_text(
        f"{sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
    )
    print(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--instrument-rules", type=Path, required=True)
    parser.add_argument("--pointer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
