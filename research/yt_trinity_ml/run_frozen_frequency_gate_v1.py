#!/usr/bin/env python3
"""Frozen 2024H1 evaluation of one pre-2024-selected frequency gate.

The gate was selected only from 2023 H1/H2 label economics.  It relaxes the
confirmed-retest geometry just enough to increase independent opportunities while
raising continuation reward/risk.  The 2024H1 period is evaluated once with the
existing causal action-value model, 500 ms latency, one global slot, and the shared
coarse cost/funding engine.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from run_frozen_period_v1 import (
    FrozenAccount,
    FrozenActionModel,
    _budget_targets,
    _final_mark,
    _fit_models,
    _score_candidates,
)
from run_research import PRIMARY, load_canonical_frames
from system.coarse import CoarseEventReplay, CoarseExecutionConfig
from system.core import FeatureConfig, RiskConfig
from system.corpus_alpha import build_corpus_features, generate_corpus_candidates_with_diagnostics
from system.metrics import summarize_account
from system.policy import GlobalSlotPolicy


@dataclass(frozen=True)
class FrozenFrequencyGate:
    reversal_target_distance_atr_min: float = 5.5
    reversal_sweep_depth_atr_min: float = 1.0
    reversal_external_rr_min: float = 1.0
    continuation_stop_distance_atr_min: float = 3.5
    continuation_path_excursion_atr_min: float = 5.0
    continuation_external_rr_min: float = 2.0


def quality_eligible(candidate: Any, gate: FrozenFrequencyGate) -> bool:
    feature = candidate.feature_row
    reward_risk = candidate.target_distance / max(candidate.stop_distance, 1e-12)
    if candidate.family.value == "LIQUIDITY_SWEEP_REVERSAL":
        return (
            float(feature.get("target_distance_atr", 0.0)) >= gate.reversal_target_distance_atr_min
            and float(feature.get("sweep_depth_atr", 0.0)) >= gate.reversal_sweep_depth_atr_min
            and reward_risk >= gate.reversal_external_rr_min
        )
    if candidate.family.value == "DISPLACEMENT_BREAK_RETEST_CONTINUATION":
        return (
            float(feature.get("stop_distance_atr", 0.0)) >= gate.continuation_stop_distance_atr_min
            and float(feature.get("path_excursion_atr", 0.0)) >= gate.continuation_path_excursion_atr_min
            and reward_risk >= gate.continuation_external_rr_min
        )
    return False


def label_gate_mask(rows: pd.DataFrame, gate: FrozenFrequencyGate) -> pd.Series:
    family = rows["family"].astype(str)
    reward_risk = pd.to_numeric(rows["raw_reward_risk"], errors="coerce")
    reversal = (
        family.eq("LIQUIDITY_SWEEP_REVERSAL")
        & pd.to_numeric(rows["target_distance_atr"], errors="coerce").ge(gate.reversal_target_distance_atr_min)
        & pd.to_numeric(rows["sweep_depth_atr"], errors="coerce").ge(gate.reversal_sweep_depth_atr_min)
        & reward_risk.ge(gate.reversal_external_rr_min)
    )
    continuation = (
        family.eq("DISPLACEMENT_BREAK_RETEST_CONTINUATION")
        & pd.to_numeric(rows["stop_distance_atr"], errors="coerce").ge(gate.continuation_stop_distance_atr_min)
        & pd.to_numeric(rows["path_excursion_atr"], errors="coerce").ge(gate.continuation_path_excursion_atr_min)
        & reward_risk.ge(gate.continuation_external_rr_min)
    )
    return reversal | continuation


def label_path_metrics(rows: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, risk_fraction: float) -> dict[str, Any]:
    selected = rows[
        (pd.to_datetime(rows["event_start"], utc=True) >= start)
        & (pd.to_datetime(rows["event_start"], utc=True) < end)
    ].copy()
    selected["event_start"] = pd.to_datetime(selected["event_start"], utc=True)
    selected["event_end"] = pd.to_datetime(selected["event_end"], utc=True)
    selected = selected.sort_values(["event_start", "symbol"], ascending=[True, False], kind="stable")

    release = start
    returns: list[float] = []
    chosen: list[dict[str, Any]] = []
    for timestamp, group in selected.groupby("event_start", sort=True):
        if timestamp < release:
            continue
        row = group.iloc[0]
        value = float(row["passive_budget_r"])
        returns.append(value)
        release = max(release, pd.Timestamp(row["event_end"]))
        chosen.append(
            {
                "timestamp": timestamp.isoformat(),
                "event_end": pd.Timestamp(row["event_end"]).isoformat(),
                "symbol": str(row["symbol"]),
                "family": str(row["family"]),
                "passive_budget_r": value,
            }
        )

    calendar_days = int((end - start).total_seconds() // 86400)
    if not returns:
        return {
            "calendar_days": calendar_days,
            "completed_trades": 0,
            "account_multiple": 1.0,
            "geometric_daily_growth": 0.0,
            "maximum_drawdown": 0.0,
            "mean_budget_r": None,
            "win_rate": None,
            "chosen": [],
        }
    values = np.asarray(returns, dtype=float)
    one_plus = 1.0 + risk_fraction * values
    if np.any(one_plus <= 0):
        raise RuntimeError("label evidence path crossed zero NAV")
    equity = np.cumprod(one_plus)
    path = np.concatenate(([1.0], equity))
    peak = np.maximum.accumulate(path)
    maximum_drawdown = float(np.max(1.0 - path / peak))
    log_growth = float(np.log(one_plus).sum())
    return {
        "calendar_days": calendar_days,
        "completed_trades": int(len(values)),
        "account_multiple": float(np.exp(log_growth)),
        "geometric_daily_growth": float(np.exp(log_growth / calendar_days) - 1.0),
        "maximum_drawdown": maximum_drawdown,
        "mean_budget_r": float(values.mean()),
        "median_budget_r": float(np.median(values)),
        "win_rate": float((values > 0).mean()),
        "chosen": chosen,
    }


def pre2024_freeze_evidence(labels_path: Path, gate: FrozenFrequencyGate) -> dict[str, Any]:
    labels = pd.read_pickle(labels_path, compression="gzip")
    labels = _budget_targets(labels)
    labels = labels[label_gate_mask(labels, gate) & labels["passive_budget_r"].notna()].copy()
    labels["event_start"] = pd.to_datetime(labels["event_start"], utc=True)
    labels["event_end"] = pd.to_datetime(labels["event_end"], utc=True)
    return {
        "selection_authority": "2023_H1_DISCOVERY_2023_H2_VALIDATION_ONLY",
        "entry_assumption": "passive label; one global slot held through resolved event_end",
        "candidate_rows": int(len(labels)),
        "by_symbol": dict(sorted(Counter(labels["symbol"].astype(str)).items())),
        "by_family": dict(sorted(Counter(labels["family"].astype(str)).items())),
        "basic_risk_1pct": {
            "2023H1": label_path_metrics(
                labels,
                pd.Timestamp("2023-01-01T00:00:00Z"),
                pd.Timestamp("2023-07-01T00:00:00Z"),
                0.01,
            ),
            "2023H2": label_path_metrics(
                labels,
                pd.Timestamp("2023-07-01T00:00:00Z"),
                pd.Timestamp("2024-01-01T00:00:00Z"),
                0.01,
            ),
        },
        "growth_risk_17pct": {
            "2023H1": label_path_metrics(
                labels,
                pd.Timestamp("2023-01-01T00:00:00Z"),
                pd.Timestamp("2023-07-01T00:00:00Z"),
                0.17,
            ),
            "2023H2": label_path_metrics(
                labels,
                pd.Timestamp("2023-07-01T00:00:00Z"),
                pd.Timestamp("2024-01-01T00:00:00Z"),
                0.17,
            ),
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end_exclusive)
    gate = FrozenFrequencyGate()
    model_config = FrozenActionModel()
    account_config = FrozenAccount(args.risk_fraction, args.maximum_leverage, args.initial_nav)

    freeze_evidence = pre2024_freeze_evidence(args.labels, gate)
    market_model, passive_model, training_labels = _fit_models(args.labels, start, model_config)
    decision, execution, funding = load_canonical_frames(
        args.data_root,
        args.repo_root,
        PRIMARY,
        tuple(args.segments),
    )

    all_period_candidates = 0
    eligible_candidates: list[Any] = []
    diagnostics: dict[str, dict[str, int]] = {}
    for symbol, frame in sorted(decision.items()):
        features = build_corpus_features(frame, FeatureConfig())
        candidates, symbol_diagnostics = generate_corpus_candidates_with_diagnostics(features, symbol)
        diagnostics[symbol] = symbol_diagnostics
        for candidate in candidates:
            if start <= candidate.timestamp < end:
                all_period_candidates += 1
                if quality_eligible(candidate, gate):
                    eligible_candidates.append(candidate)
    eligible_candidates.sort(key=lambda row: (row.timestamp, row.symbol, row.family.value, row.side))

    scored, score_rows, action_counts = _score_candidates(
        eligible_candidates,
        market_model,
        passive_model,
        model_config,
    )
    execution_config = CoarseExecutionConfig()
    account = CoarseEventReplay(execution, execution_config).run(
        scored,
        GlobalSlotPolicy(),
        RiskConfig(account_config.risk_fraction, account_config.maximum_leverage, 0.001, 0.001),
        start,
        end,
        initial_nav=account_config.initial_nav,
        funding=funding,
        instrument_rules={"BTCUSDT": (0.001, 0.001), "ETHUSDT": (0.01, 0.01)},
    )
    final_mark, final_closeout = _final_mark(account, execution, end, execution_config)
    metrics = summarize_account(
        account,
        start,
        end,
        final_mark,
        final_closeout_price=final_closeout,
        final_closeout_fee_rate=execution_config.taker_fee_rate if final_closeout is not None else 0.0,
    )

    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "stage": args.stage,
        "scientific_source_sha": args.scientific_source_sha,
        "training_label_artifact_id": args.training_label_artifact_id,
        "pre2024_freeze_evidence": freeze_evidence,
        "evaluation_start": start.isoformat(),
        "evaluation_end_exclusive": end.isoformat(),
        "system_contract": {
            "quality_gate": asdict(gate),
            "action_model": asdict(model_config),
            "account": asdict(account_config),
            "model_update_during_period": False,
            "entry_latency_ms": execution_config.activation_latency_ms,
            "global_entry_slots": 1,
        },
        "training_rows": int(len(training_labels)),
        "all_structural_period_candidates": int(all_period_candidates),
        "quality_eligible_candidates": int(len(eligible_candidates)),
        "ml_threshold_pass_candidates": int(sum(row["passes_threshold"] for row in score_rows)),
        "predicted_action_counts_before_slot": dict(action_counts),
        "candidate_generation_diagnostics": diagnostics,
        "metrics": metrics.as_dict(),
        "closed_trades": [asdict(trade) for trade in account.closed_trades],
        "daily_nav": [asdict(record) for record in account.daily_nav],
        "candidate_scores": score_rows,
        "ranking_effect": args.ranking_effect,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    result_path = args.output / "FROZEN_FREQUENCY_GATE_RESULT.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (args.output / "FROZEN_FREQUENCY_GATE_RESULT.sha256").write_text(
        f"{hashlib.sha256(result_path.read_bytes()).hexdigest()}  {result_path.name}\n",
        encoding="utf-8",
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segments", nargs="+", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end-exclusive", required=True)
    parser.add_argument("--initial-nav", type=float, default=10000.0)
    parser.add_argument("--risk-fraction", type=float, default=0.17)
    parser.add_argument("--maximum-leverage", type=float, default=20.0)
    parser.add_argument("--stage", default="2024_H1_FROZEN_FREQUENCY_GATE_V1_COARSE_PROVISIONAL")
    parser.add_argument("--scientific-source-sha", default="SELF_GITHUB_SHA")
    parser.add_argument("--training-label-artifact-id", type=int, default=8643192491)
    parser.add_argument("--ranking-effect", default="PROVISIONAL_NOT_EVENT_TAPE_VALIDATED")
    args = parser.parse_args(argv)
    result = run(args)
    print(
        json.dumps(
            {
                "pre2024": result["pre2024_freeze_evidence"],
                "metrics": result["metrics"],
                "quality_eligible_candidates": result["quality_eligible_candidates"],
                "ml_threshold_pass_candidates": result["ml_threshold_pass_candidates"],
                "actions": result["predicted_action_counts_before_slot"],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
