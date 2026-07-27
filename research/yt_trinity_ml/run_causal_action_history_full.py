#!/usr/bin/env python3
"""Continuously replay the exact 2021-2023 frozen SMC action survivor.

The model, score quantile, exit variant, risk fraction and maximum leverage are all
fixed before 2024. NAV begins at 10,000 USDT on 2024-01-01 and is never reset through
2026-06-30. This remains a coarse one-minute screen pending event-tape validation.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from run_causal_action_fast import _rows_fast
from run_causal_action_history import (
    BASE_START,
    CALIBRATION_END,
    EVALUATION_START,
    EXIT_VARIANTS,
    PRE2024_SEGMENTS,
    SELECTION_END,
    SELECTION_START,
    _period,
    _score,
)
from run_causal_action_v1 import ScreenConfig, _account, _feature_columns, _jsonable
from run_research import PRIMARY, load_canonical_frames, load_instrument_rules
from system.causal_action_candidates import generate_causal_action_candidates_by_symbol
from system.causal_action_history_model import ExplicitHistoryActionValueModel
from system.core import FeatureConfig


EVALUATION_SEGMENTS = (
    "2024_H1",
    "2024_H2",
    "2025_H1",
    "2025_H2",
    "2026_H1",
)
EVALUATION_END = pd.Timestamp("2026-07-01T00:00:00Z")
HALF_YEARS = (
    ("2024_H1", "2024-01-01T00:00:00Z", "2024-07-01T00:00:00Z"),
    ("2024_H2", "2024-07-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    ("2025_H1", "2025-01-01T00:00:00Z", "2025-07-01T00:00:00Z"),
    ("2025_H2", "2025-07-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    ("2026_H1", "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z"),
)


def _nav_events(records: list[dict[str, Any]]) -> list[tuple[pd.Timestamp, float]]:
    nav = 10000.0
    events = [(EVALUATION_START, nav)]
    for row in sorted(records, key=lambda item: pd.Timestamp(item["event_end"])):
        if int(row.get("filled", 0)):
            nav *= 1.0 + float(row.get("return", 0.0))
        events.append((pd.Timestamp(row["event_end"]), nav))
    return events


def _nav_at(events: list[tuple[pd.Timestamp, float]], timestamp: pd.Timestamp) -> float:
    nav = 10000.0
    for event_time, value in events:
        if event_time > timestamp:
            break
        nav = float(value)
    return nav


def _half_years(account: dict[str, Any]) -> dict[str, Any]:
    events = _nav_events(account["records"])
    result: dict[str, Any] = {}
    for name, raw_start, raw_end in HALF_YEARS:
        start = pd.Timestamp(raw_start)
        end = pd.Timestamp(raw_end)
        start_nav = _nav_at(events, start)
        end_nav = _nav_at(events, end)
        days = max(1, (end - start).days)
        geometric = (
            -1.0
            if start_nav <= 0 or end_nav <= 0
            else float(np.exp(np.log(end_nav / start_nav) / days) - 1.0)
        )
        period_records = [
            row
            for row in account["records"]
            if start <= pd.Timestamp(row["activation"]) < end
        ]
        result[name] = {
            "start_nav": start_nav,
            "end_nav": end_nav,
            "nav_multiple": end_nav / start_nav if start_nav > 0 else 0.0,
            "geometric_daily_growth": geometric,
            "decisions": len(period_records),
            "filled_trades": sum(int(row.get("filled", 0)) for row in period_records),
        }
    return result


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    pointer = json.loads(args.pointer.read_text(encoding="utf-8"))
    source_result = pointer.get("result") or {}
    h1 = source_result.get("result_2024_h1") or {}
    if (
        pointer.get("job_status") != "success"
        or int(pointer.get("exit_code", 99)) != 0
        or float(h1.get("geometric_daily_growth", 0.0)) <= 0
    ):
        result = {
            "schema_version": 1,
            "stage": "EXPLICIT_HISTORY_FULL_PERIOD_NOT_OPENED",
            "reason": "completed positive 2024H1 explicit-history result is absent",
            "ranking_effect": "NONE",
        }
        (args.output / "CAUSAL_ACTION_HISTORY_FULL_RESULT.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0

    selected = source_result["selected_pre2024"]
    variant = str(selected["variant"])
    quantile = float(selected["quantile"])
    risk_fraction = float(selected["risk_fraction"])
    maximum_leverage = float(selected["maximum_leverage"])
    if variant not in EXIT_VARIANTS:
        raise RuntimeError(f"unknown frozen exit variant: {variant}")

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
        (variant,),
        screen,
    )
    feature_names = _feature_columns(rows_pre)
    production_base = _period(
        rows_pre,
        BASE_START,
        CALIBRATION_END,
    )
    production_calibration = _period(
        rows_pre,
        SELECTION_START,
        SELECTION_END,
    )
    model = ExplicitHistoryActionValueModel().fit(
        production_base,
        production_calibration,
        feature_names,
    )
    scored_calibration = _score(model, production_calibration)
    frozen_threshold = max(
        0.0,
        float(scored_calibration["score"].quantile(quantile)),
    )
    expected_threshold = float(
        source_result["production_refit_contract"]["frozen_threshold"]
    )
    if not np.isclose(frozen_threshold, expected_threshold, rtol=1e-10, atol=1e-12):
        raise RuntimeError(
            f"frozen threshold mismatch: rebuilt={frozen_threshold} pointer={expected_threshold}"
        )
    if model.fingerprint() != source_result["production_refit_contract"]["model_fingerprint"]:
        raise RuntimeError("pre-2024 production model fingerprint mismatch")

    decision_eval, execution_eval, funding_eval = load_canonical_frames(
        args.data_root,
        args.repo_root,
        PRIMARY,
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
        args.output / "SCORED_ACTIONS_2024_2026H1.parquet",
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

    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "stage": "2024_TO_2026H1_EXPLICIT_HISTORY_CAUSAL_ACTION_COARSE_NOT_RANKABLE",
        "evaluation_start": EVALUATION_START,
        "evaluation_end_exclusive": EVALUATION_END,
        "initial_nav": 10000.0,
        "continuous_nav_no_resets": True,
        "all_utc_calendar_days_in_growth_denominator": True,
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
            "ADVANCE_TO_EVENT_TAPE_AND_LIVE_IDENTICAL_ENGINE"
            if account["geometric_daily_growth"] >= 0.01
            else "KEEP_UNIFIED_SMC_NARRATIVE_CONTINUE_IMPLEMENTATION_REFINEMENT"
        ),
        "known_coarse_limitations": [
            "one-minute first-passage replay rather than event-tape queue and depth",
            "half-year diagnostics mark NAV only at realized account events",
            "official ranking remains closed until event-tape validation",
        ],
        "ranking_effect": "NONE_COARSE_1M_NOT_RANKABLE",
    }
    path = args.output / "CAUSAL_ACTION_HISTORY_FULL_RESULT.json"
    path.write_text(
        json.dumps(_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output / "CAUSAL_ACTION_HISTORY_FULL_RESULT.sha256").write_text(
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
    parser.add_argument("--pointer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
