#!/usr/bin/env python3
"""Replay the exact pre-2024 causal-action survivor over 2024 through 2026H1."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from run_causal_action_v1 import (
    ScreenConfig,
    _account,
    _feature_columns,
    _fit,
    _score_rows,
    _jsonable,
    _rows,
)
from run_research import PRIMARY, load_canonical_frames, load_instrument_rules
from system.core import FeatureConfig
from system.research_pipeline import generate_candidates_by_symbol


SEGMENTS = ("2024_H1", "2024_H2", "2025_H1", "2025_H2", "2026_H1")
BOUNDARIES = (
    ("2024_H1", "2024-01-01T00:00:00Z", "2024-07-01T00:00:00Z"),
    ("2024_H2", "2024-07-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    ("2025_H1", "2025-01-01T00:00:00Z", "2025-07-01T00:00:00Z"),
    ("2025_H2", "2025-07-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    ("2026_H1", "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z"),
)


def _nav_path(records: list[dict[str, Any]]) -> list[tuple[pd.Timestamp, float]]:
    nav = 10000.0
    result = [(pd.Timestamp("2024-01-01T00:00:00Z"), nav)]
    for row in records:
        if int(row.get("filled", 0)):
            nav *= 1.0 + float(row.get("return", 0.0))
        result.append((pd.Timestamp(row["event_end"]), nav))
    return result


def _nav_at(path: list[tuple[pd.Timestamp, float]], timestamp: pd.Timestamp) -> float:
    value = 10000.0
    for time, nav in path:
        if time > timestamp:
            break
        value = nav
    return value


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    pointer = json.loads(args.pointer.read_text())
    first = pointer.get("result") or {}
    h1 = first.get("result_2024_h1") or {}
    if float(h1.get("geometric_daily_growth", 0.0)) <= 0:
        payload = {
            "schema_version": 1,
            "stage": "FULL_PERIOD_NOT_OPENED",
            "reason": "causal-action 2024H1 coarse result is nonpositive or unavailable",
            "source_pointer": str(args.pointer),
            "ranking_effect": "NONE",
        }
        (args.output / "CAUSAL_ACTION_FULL_RESULT.json").write_text(json.dumps(payload, indent=2) + "\n")
        return 0

    selected = first["selected_pre2024"]
    variant = str(selected["variant"])
    quantile = float(selected["quantile"])
    risk_fraction = float(selected["risk_fraction"])
    maximum_leverage = float(selected["maximum_leverage"])

    rules = load_instrument_rules(args.instrument_rules, PRIMARY)
    rule_map = {row.symbol: (row.quantity_step, row.minimum_quantity) for row in rules}
    screen = ScreenConfig()

    decision_2023, execution_2023, funding_2023 = load_canonical_frames(
        args.data_root, args.repo_root, PRIMARY, ("PRE_2024_2023",)
    )
    _, candidates_2023 = generate_candidates_by_symbol(decision_2023, FeatureConfig())
    rows_2023 = _rows(
        candidates_2023, execution_2023, funding_2023,
        pd.Timestamp("2024-01-01T00:00:00Z"), (variant,), screen,
    )
    pre_end = pd.Timestamp("2024-01-01T00:00:00Z")
    training = rows_2023[(rows_2023["activation"] < pre_end) & (rows_2023["event_end"] < pre_end)].copy()
    features = _feature_columns(training)
    model = _fit(training, features)
    training = _score_rows(model, training, features)
    threshold = float(training["score"].quantile(quantile))

    decision, execution, funding = load_canonical_frames(
        args.data_root, args.repo_root, PRIMARY, SEGMENTS
    )
    _, candidates = generate_candidates_by_symbol(decision, FeatureConfig())
    rows = _rows(
        candidates, execution, funding,
        pd.Timestamp("2026-07-01T00:00:00Z"), (variant,), screen,
    )
    if rows.empty:
        raise RuntimeError("no continuous evaluation action rows")
    rows = _score_rows(model, rows, features)
    rows.to_parquet(args.output / "ACTION_LABELS_2024_2026H1.parquet", index=False)

    start = pd.Timestamp("2024-01-01T00:00:00Z")
    end = pd.Timestamp("2026-07-01T00:00:00Z")
    account = _account(rows, start, end, threshold, risk_fraction, maximum_leverage, rule_map)
    path = _nav_path(account["records"])
    half_years: dict[str, Any] = {}
    for name, raw_start, raw_end in BOUNDARIES:
        period_start = pd.Timestamp(raw_start)
        period_end = pd.Timestamp(raw_end)
        nav_start = _nav_at(path, period_start)
        nav_end = _nav_at(path, period_end)
        days = max(1, (period_end - period_start).days)
        growth = -1.0 if nav_start <= 0 or nav_end <= 0 else float(np.exp(np.log(nav_end / nav_start) / days) - 1.0)
        half_years[name] = {
            "start_nav": nav_start,
            "end_nav": nav_end,
            "nav_multiple": nav_end / nav_start if nav_start > 0 else 0.0,
            "geometric_daily_growth": growth,
            "filled_trades": sum(
                int(row.get("filled", 0))
                for row in account["records"]
                if period_start <= pd.Timestamp(row["activation"]) < period_end
            ),
        }

    result = {
        "schema_version": 1,
        "stage": "2024_TO_2026H1_CAUSAL_ACTION_COARSE_NOT_RANKABLE",
        "evaluation_start": start,
        "evaluation_end_exclusive": end,
        "initial_nav": 10000.0,
        "continuous_account": account,
        "half_years": half_years,
        "selected_pre2024": {
            "variant": variant,
            "quantile": quantile,
            "frozen_threshold": threshold,
            "risk_fraction": risk_fraction,
            "maximum_leverage": maximum_leverage,
            "feature_count": len(features),
            "grouped_action_model_fingerprint": model.fingerprint(),
            "grouped_action_model_diagnostics": model.diagnostics(),
        },
        "candidate_count": len(candidates),
        "action_rows": len(rows),
        "target_exceeded_coarse": account["geometric_daily_growth"] >= 0.01,
        "decision": (
            "ADVANCE_TO_EVENT_TAPE_AND_LIVE_IDENTICAL_ENGINE"
            if account["geometric_daily_growth"] >= 0.01
            else "KEEP_UNIFIED_SMC_NARRATIVE_CONTINUE_IMPLEMENTATION_AND_MODEL_REFINEMENT"
        ),
        "ranking_effect": "NONE_COARSE_1M_NOT_RANKABLE",
    }
    path_out = args.output / "CAUSAL_ACTION_FULL_RESULT.json"
    path_out.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    (args.output / "CAUSAL_ACTION_FULL_RESULT.sha256").write_text(f"{sha256(path_out.read_bytes()).hexdigest()}  {path_out.name}\n")
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
