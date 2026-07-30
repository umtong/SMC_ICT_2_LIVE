#!/usr/bin/env python3
"""Evaluate the frozen SMC/ICT quality gate with causal ML priority ranking.

The family-specific gate, BTC/ETH universe, passive entry, account risk, leverage,
fees and 500 ms activation latency are fixed from information available through
2023-12-31.  A small HGBT trained only on quality-gated pre-period labels predicts
passive planned-loss-budget R.  It does not add an abstention threshold: every
eligible setup remains tradable, while the prediction only resolves simultaneous
cross-symbol priority in the single global entry slot.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from math import exp
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from run_frozen_period_v1 import (
    FEATURE_COLUMNS,
    FrozenQualityGate,
    _budget_targets,
    _candidate_features,
    _final_mark,
    _quality_eligible,
)
from run_research import PRIMARY, load_canonical_frames
from system.coarse import CoarseEventReplay, CoarseExecutionConfig
from system.core import FeatureConfig, RiskConfig
from system.corpus_alpha import build_corpus_features, generate_corpus_candidates_with_diagnostics
from system.metrics import summarize_account
from system.model import ScoredCandidate
from system.policy import GlobalSlotPolicy


def label_quality_mask(rows: pd.DataFrame, gate: FrozenQualityGate) -> pd.Series:
    family = rows["family"].astype(str)
    reversal = family.eq("LIQUIDITY_SWEEP_REVERSAL")
    rr = pd.to_numeric(rows["raw_reward_risk"], errors="coerce")
    reversal_mask = (
        reversal
        & (pd.to_numeric(rows["target_distance_atr"], errors="coerce") >= gate.reversal_target_distance_atr_min)
        & (pd.to_numeric(rows["sweep_depth_atr"], errors="coerce") >= gate.reversal_sweep_depth_atr_min)
        & (rr >= gate.reversal_external_rr_min)
    )
    continuation_mask = (
        ~reversal
        & (pd.to_numeric(rows["stop_distance_atr"], errors="coerce") >= gate.continuation_stop_distance_atr_min)
        & (pd.to_numeric(rows["path_excursion_atr"], errors="coerce") >= gate.continuation_path_excursion_atr_min)
        & (rr >= gate.continuation_external_rr_min)
    )
    return reversal_mask | continuation_mask


def fit_priority_model(labels_path: Path, cutoff: pd.Timestamp, gate: FrozenQualityGate) -> tuple[HistGradientBoostingRegressor, pd.DataFrame]:
    labels = pd.read_pickle(labels_path, compression="gzip").reset_index(drop=True)
    labels["event_end"] = pd.to_datetime(labels["event_end"], utc=True)
    labels = _budget_targets(labels)
    labels = labels[
        (labels["event_end"] < cutoff)
        & label_quality_mask(labels, gate)
        & labels["passive_budget_r"].notna()
    ].copy()
    if len(labels) < 30:
        raise RuntimeError(f"insufficient quality-gated pre-period labels: {len(labels)}")
    x = labels.reindex(columns=FEATURE_COLUMNS).replace([np.inf, -np.inf], np.nan)
    model = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.05,
        max_leaf_nodes=7,
        max_iter=120,
        min_samples_leaf=8,
        l2_regularization=5.0,
        random_state=20260727,
    )
    model.fit(x, labels["passive_budget_r"].astype(float))
    return model, labels


def score_candidates(candidates: list[Any], model: HistGradientBoostingRegressor) -> tuple[list[ScoredCandidate], list[dict[str, Any]]]:
    if not candidates:
        return [], []
    matrix = pd.DataFrame([_candidate_features(candidate) for candidate in candidates], columns=FEATURE_COLUMNS)
    matrix = matrix.replace([np.inf, -np.inf], np.nan)
    predictions = model.predict(matrix)
    scored: list[ScoredCandidate] = []
    rows: list[dict[str, Any]] = []
    for candidate, prediction in zip(candidates, predictions, strict=True):
        prediction = float(prediction)
        priority = 1.0 / (1.0 + exp(-float(np.clip(prediction, -20.0, 20.0))))
        scored.append(
            ScoredCandidate(
                candidate=candidate,
                win_probability=0.5,
                expected_net_r=prediction,
                passive_fill_probability=1.0,
                expected_log_growth=prediction,
                lower_confidence_score=priority,
                passive_win_probability=0.5,
                market_expected_log_growth=-1.0,
                passive_expected_log_growth=prediction,
                market_lower_confidence_score=-1.0,
                passive_lower_confidence_score=priority,
                preferred_action="PASSIVE_RETEST",
            )
        )
        rows.append(
            {
                "timestamp": candidate.timestamp,
                "symbol": candidate.symbol,
                "family": candidate.family.value,
                "side": candidate.side,
                "entry_reference": candidate.entry_reference,
                "stop_reference": candidate.stop_reference,
                "target_reference": candidate.target_reference,
                "predicted_passive_budget_r": prediction,
                "priority_score": priority,
            }
        )
    return scored, rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end_exclusive)
    if start.tz is None or end.tz is None:
        raise ValueError("evaluation timestamps must include timezone")
    gate = FrozenQualityGate()
    model, training = fit_priority_model(args.labels, start, gate)
    decision, execution, funding = load_canonical_frames(
        args.data_root, args.repo_root, PRIMARY, tuple(args.segments)
    )

    diagnostics: dict[str, dict[str, int]] = {}
    all_period_candidates = 0
    eligible: list[Any] = []
    for symbol, frame in sorted(decision.items()):
        features = build_corpus_features(frame, FeatureConfig())
        candidates, symbol_diagnostics = generate_corpus_candidates_with_diagnostics(features, symbol)
        diagnostics[symbol] = symbol_diagnostics
        for candidate in candidates:
            if start <= candidate.timestamp < end:
                all_period_candidates += 1
                if _quality_eligible(candidate, gate):
                    eligible.append(candidate)
    eligible.sort(key=lambda row: (row.timestamp, row.symbol, row.family.value, row.side))
    scored, score_rows = score_candidates(eligible, model)

    execution_config = CoarseExecutionConfig()
    account = CoarseEventReplay(execution, execution_config).run(
        scored,
        GlobalSlotPolicy(),
        RiskConfig(args.risk_fraction, args.maximum_leverage, 0.001, 0.001),
        start,
        end,
        initial_nav=args.initial_nav,
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

    args.output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(score_rows).to_csv(args.output / "CANDIDATE_SCORES.csv", index=False)
    pd.DataFrame([asdict(row) for row in account.closed_trades]).to_csv(
        args.output / "CLOSED_TRADES.csv", index=False
    )
    pd.DataFrame([asdict(row) for row in account.daily_nav]).to_csv(
        args.output / "DAILY_NAV.csv", index=False
    )
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "stage": args.stage,
        "evaluation_start": start.isoformat(),
        "evaluation_end_exclusive": end.isoformat(),
        "training_cutoff": start.isoformat(),
        "training_quality_gate_rows": int(len(training)),
        "training_passive_budget_r_mean": float(training["passive_budget_r"].mean()),
        "training_passive_budget_r_median": float(training["passive_budget_r"].median()),
        "universe": list(PRIMARY),
        "entry_action": "PASSIVE_RETEST_FIXED",
        "ml_role": "rank simultaneous quality-eligible BTC/ETH setups; no ML abstention",
        "quality_gate": asdict(gate),
        "risk_fraction": args.risk_fraction,
        "maximum_leverage": args.maximum_leverage,
        "all_period_candidates": all_period_candidates,
        "eligible_candidates": len(eligible),
        "eligible_by_symbol": dict(sorted(Counter(row.symbol for row in eligible).items())),
        "eligible_by_family": dict(sorted(Counter(row.family.value for row in eligible).items())),
        "prediction_min": float(min((row["predicted_passive_budget_r"] for row in score_rows), default=np.nan)),
        "prediction_median": float(np.median([row["predicted_passive_budget_r"] for row in score_rows])) if score_rows else None,
        "prediction_max": float(max((row["predicted_passive_budget_r"] for row in score_rows), default=np.nan)),
        "metrics": metrics.as_dict(),
        "diagnostics": diagnostics,
        "ranking_effect": "PROVISIONAL_COARSE_ONLY",
    }
    (args.output / "QUALITY_GATE_ML_RANK_RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segments", nargs="+", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end-exclusive", required=True)
    parser.add_argument("--risk-fraction", type=float, default=0.17)
    parser.add_argument("--maximum-leverage", type=float, default=20.0)
    parser.add_argument("--initial-nav", type=float, default=10000.0)
    parser.add_argument("--stage", default="2024_H1_FIXED_QUALITY_GATE_ML_RANK_COARSE_PROVISIONAL")
    result = run(parser.parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
