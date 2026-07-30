#!/usr/bin/env python3
"""Conditionally test SOL/XRP without changing the unified SMC/ICT premise.

Symbol-set selection uses only 2023H2 after 2021-2022 base learning and 2023H1
calibration. One frozen set is then replayed on untouched 2024H1 with a single global
entry slot. No 2020 data is used.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from run_causal_action_fast import _rows_fast
from run_causal_action_history import (
    BASE_START,
    CALIBRATION_END,
    EVALUATION_END,
    EVALUATION_START,
    EXIT_VARIANTS,
    PRE2024_SEGMENTS,
    SELECTION_END,
    SELECTION_START,
    _history_feature_columns,
    _period,
    _score,
    _select_pre2024,
)
from run_causal_action_v1 import ScreenConfig, _account, _jsonable
from run_research import load_canonical_frames, load_instrument_rules
from system.causal_action_candidates import generate_causal_action_candidates_by_symbol
from system.causal_action_history_model import ExplicitHistoryActionValueModel
from system.core import FeatureConfig


ALL_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
SYMBOL_SETS = {
    "BTC_ETH": ("BTCUSDT", "ETHUSDT"),
    "BTC_ETH_SOL": ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    "BTC_ETH_XRP": ("BTCUSDT", "ETHUSDT", "XRPUSDT"),
    "BTC_ETH_SOL_XRP": ALL_SYMBOLS,
}


def _selection_key(row: dict[str, Any]) -> tuple[float, float, float, int]:
    account = row["selected_pre2024"]["optimized_account_2023_h2"]
    return (
        float(account["geometric_daily_growth"]),
        float(account["nav_multiple"]),
        -float(account["maximum_drawdown_at_realized_events"]),
        -len(row["symbols"]),
    )


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    source_pointer = json.loads(args.source_pointer.read_text(encoding="utf-8"))
    source_result = source_pointer.get("result") or {}
    alt_ready = json.loads(args.alt_ready.read_text(encoding="utf-8"))
    if alt_ready.get("status") != "PASS_COMPLETE":
        raise RuntimeError("conditional SOL/XRP history is not complete")
    if alt_ready.get("source_btc_eth_result_sha256") != source_pointer.get("result_sha256"):
        raise RuntimeError("conditional history was not authorized by the current BTC/ETH result")

    rules = load_instrument_rules(args.instrument_rules, ALL_SYMBOLS)
    rule_map = {
        rule.symbol: (rule.quantity_step, rule.minimum_quantity)
        for rule in rules
    }
    screen = ScreenConfig()

    decision_pre, execution_pre, funding_pre = load_canonical_frames(
        args.data_root,
        args.repo_root,
        ALL_SYMBOLS,
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
        raise RuntimeError("no multi-symbol causal action rows")
    rows_pre.to_parquet(args.output / "MULTISYMBOL_ACTION_LABELS_2021_2023.parquet", index=False)
    feature_names = _history_feature_columns(rows_pre)

    set_results: list[dict[str, Any]] = []
    for set_name, symbols in SYMBOL_SETS.items():
        scoped = rows_pre[rows_pre["symbol"].astype(str).isin(symbols)].copy()
        selected, attempts, raw = _select_pre2024(scoped, feature_names, rule_map)
        set_results.append(
            {
                "set_name": set_name,
                "symbols": list(symbols),
                "selected_pre2024": selected,
                "selection_attempts": attempts,
                "raw_pre2024": raw,
            }
        )

    survivors = [row for row in set_results if row["selected_pre2024"] is not None]
    base_result = next(row for row in set_results if row["set_name"] == "BTC_ETH")
    if not survivors:
        result = {
            "schema_version": 1,
            "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
            "stage": "CONDITIONAL_MULTISYMBOL_PRE2024_COARSE_NOT_RANKABLE",
            "decision": "NO_POSITIVE_MULTISYMBOL_CAUSAL_SURVIVOR",
            "symbol_set_results": set_results,
            "source_btc_eth_result_sha256": source_pointer.get("result_sha256"),
            "official_2024_h1_opened": False,
            "target_exceeded_coarse": False,
            "ranking_effect": "NONE_COARSE_1M_NOT_RANKABLE",
        }
        path = args.output / "CAUSAL_ACTION_MULTISYMBOL_RESULT.json"
        path.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        (args.output / "CAUSAL_ACTION_MULTISYMBOL_RESULT.sha256").write_text(
            f"{sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        )
        return 0

    selected_set = max(survivors, key=_selection_key)
    selected = selected_set["selected_pre2024"]
    symbols = tuple(selected_set["symbols"])
    variant = str(selected["variant"])
    quantile = float(selected["quantile"])
    scoped_pre = rows_pre[
        rows_pre["symbol"].astype(str).isin(symbols)
        & rows_pre["exit_variant"].astype(str).eq(variant)
    ].copy()
    production_base = _period(scoped_pre, BASE_START, CALIBRATION_END)
    production_calibration = _period(scoped_pre, SELECTION_START, SELECTION_END)
    model = ExplicitHistoryActionValueModel().fit(
        production_base,
        production_calibration,
        feature_names,
    )
    scored_calibration = _score(model, production_calibration)
    frozen_threshold = max(0.0, float(scored_calibration["score"].quantile(quantile)))

    decision_2024, execution_2024, funding_2024 = load_canonical_frames(
        args.data_root,
        args.repo_root,
        symbols,
        ("2024_H1",),
    )
    _, candidates_2024, diagnostics_2024 = generate_causal_action_candidates_by_symbol(
        decision_2024,
        FeatureConfig(),
    )
    rows_2024 = _rows_fast(
        candidates_2024,
        execution_2024,
        funding_2024,
        EVALUATION_END,
        (variant,),
        screen,
    )
    scored_2024 = _score(model, rows_2024)
    account_2024 = _account(
        scored_2024,
        EVALUATION_START,
        EVALUATION_END,
        frozen_threshold,
        float(selected["risk_fraction"]),
        float(selected["maximum_leverage"]),
        rule_map,
    )
    scored_2024.to_parquet(args.output / "MULTISYMBOL_SCORED_ACTIONS_2024_H1.parquet", index=False)

    baseline_pre_growth = None
    if base_result["selected_pre2024"] is not None:
        baseline_pre_growth = float(
            base_result["selected_pre2024"]["optimized_account_2023_h2"][
                "geometric_daily_growth"
            ]
        )
    selected_pre_growth = float(
        selected["optimized_account_2023_h2"]["geometric_daily_growth"]
    )
    alt_included = any(symbol in {"SOLUSDT", "XRPUSDT"} for symbol in symbols)
    conditional_inclusion_justified_pre2024 = (
        alt_included
        and (
            baseline_pre_growth is None
            or selected_pre_growth > baseline_pre_growth
        )
    )

    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "stage": "CONDITIONAL_MULTISYMBOL_2024H1_COARSE_NOT_RANKABLE",
        "model_contract": {
            "base_learning": "2021-01-01 through 2022-12-31",
            "calibration": "2023H1",
            "symbol_set_exit_threshold_risk_selection": "2023H2",
            "evaluation": "untouched 2024H1",
            "global_entry_slot": 1,
            "excluded_history": "2020 and earlier",
        },
        "source_btc_eth_result_sha256": source_pointer.get("result_sha256"),
        "symbol_set_results": set_results,
        "selected_symbol_set": selected_set["set_name"],
        "selected_symbols": list(symbols),
        "selected_pre2024": selected,
        "baseline_btc_eth_pre2024_growth": baseline_pre_growth,
        "selected_pre2024_growth": selected_pre_growth,
        "conditional_alt_inclusion_justified_pre2024": conditional_inclusion_justified_pre2024,
        "production_refit_contract": {
            "variant": variant,
            "score_quantile": quantile,
            "frozen_threshold": frozen_threshold,
            "risk_fraction": float(selected["risk_fraction"]),
            "maximum_leverage": float(selected["maximum_leverage"]),
            "model_fingerprint": model.fingerprint(),
            "model_diagnostics": model.diagnostics(),
        },
        "candidate_diagnostics_pre2024": diagnostics_pre,
        "candidate_diagnostics_2024_h1": diagnostics_2024,
        "result_2024_h1": account_2024,
        "official_2024_h1_opened": True,
        "target_exceeded_coarse": account_2024["geometric_daily_growth"] >= 0.01,
        "decision": (
            "ADVANCE_MULTISYMBOL_SURVIVOR_TO_EVENT_TAPE_AND_CONTINUOUS_EVALUATION"
            if account_2024["geometric_daily_growth"] > 0
            else "DO_NOT_INCLUDE_ALT_SYMBOLS_FROM_THIS_FROZEN_SELECTION"
        ),
        "ranking_effect": "NONE_COARSE_1M_NOT_RANKABLE",
    }
    path = args.output / "CAUSAL_ACTION_MULTISYMBOL_RESULT.json"
    path.write_text(
        json.dumps(_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output / "CAUSAL_ACTION_MULTISYMBOL_RESULT.sha256").write_text(
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
    parser.add_argument("--source-pointer", type=Path, required=True)
    parser.add_argument("--alt-ready", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
