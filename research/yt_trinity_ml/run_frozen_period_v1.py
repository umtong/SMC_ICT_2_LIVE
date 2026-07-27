#!/usr/bin/env python3
"""Frozen causal SMC/ICT quality-gate + cost-aware ML half-year evaluator.

The scientific contract is selected using data available through 2023-12-31:
- one unified SMC/ICT narrative from the complete 186-video corpus;
- deterministic family-specific structural quality gates;
- two causal HGBT regressors trained only on resolved pre-period labels;
- a fixed cost-aware action threshold;
- one global entry slot, fixed 500 ms activation latency, realistic coarse costs;
- fixed risk fraction and leverage for the entire evaluated half-year.
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
from sklearn.ensemble import HistGradientBoostingRegressor

from run_research import PRIMARY, load_canonical_frames
from system.coarse import CoarseEventReplay, CoarseExecutionConfig, coarse_closeout_price
from system.core import FeatureConfig, RiskConfig
from system.corpus_alpha import build_corpus_features, generate_corpus_candidates_with_diagnostics
from system.metrics import summarize_account
from system.model import ScoredCandidate
from system.policy import GlobalSlotPolicy


FEATURE_COLUMNS = (
    "raw_reward_risk",
    "atr_fraction",
    "stop_distance_atr",
    "target_distance_atr",
    "path_excursion_atr",
    "sweep_depth_atr",
    "liquidity_quality",
    "draw_target_quality",
    "htf_bias_alignment",
    "dealing_range_side_alignment",
    "session_code",
    "killzone",
    "pd_array_kind",
    "entry_confirmation_kind",
    "zone_width_atr",
    "zone_midpoint_distance_atr",
    "retest_depth_fraction",
    "narrative_age_bars",
    "confirmation_age_bars",
    "ob_search_age_bars",
    "mitigation_count",
    "volume_z",
    "confirmation_volume_z",
    "bollinger_bandwidth",
    "realized_vol_20",
    "compression_ratio_96",
    "range_expansion_ratio_20",
    "side",
    "family_liquidity_sweep",
    "symbol_btc",
    "utc_hour_sin",
    "utc_hour_cos",
)


@dataclass(frozen=True)
class FrozenQualityGate:
    reversal_target_distance_atr_min: float = 5.5
    reversal_sweep_depth_atr_min: float = 1.2
    reversal_external_rr_min: float = 1.0
    continuation_stop_distance_atr_min: float = 4.0
    continuation_path_excursion_atr_min: float = 6.0
    continuation_external_rr_min: float = 1.25


@dataclass(frozen=True)
class FrozenActionModel:
    threshold_budget_r: float = -0.20
    max_leaf_nodes: int = 7
    min_samples_leaf: int = 40
    max_iter: int = 100
    learning_rate: float = 0.05
    l2_regularization: float = 5.0
    random_state: int = 20260727


@dataclass(frozen=True)
class FrozenAccount:
    risk_fraction: float = 0.17
    maximum_leverage: float = 20.0
    initial_nav: float = 10000.0


def _budget_targets(rows: pd.DataFrame) -> pd.DataFrame:
    """Convert stop-distance labels to planned-loss-budget R."""
    out = rows.copy()
    stop_fraction = pd.to_numeric(out["stop_distance_fraction"], errors="coerce").clip(lower=1e-9)
    side = pd.to_numeric(out["side"], errors="coerce")
    stop_ratio = 1.0 - side * stop_fraction
    market_planned_loss = stop_fraction + 0.00075 + stop_ratio * 0.00095
    passive_planned_loss = stop_fraction + 0.00020 + stop_ratio * 0.00095
    out["market_budget_r"] = (
        pd.to_numeric(out["market_net_r"], errors="coerce") * stop_fraction / market_planned_loss
    )
    out["passive_budget_r"] = (
        pd.to_numeric(out["passive_net_r"], errors="coerce") * stop_fraction / passive_planned_loss
    )
    return out


def _candidate_features(candidate: Any) -> dict[str, float]:
    values = {
        str(key): float(value)
        for key, value in candidate.feature_row.items()
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)
    }
    values.update(
        {
            "raw_reward_risk": candidate.target_distance / max(candidate.stop_distance, 1e-12),
            "side": float(candidate.side),
            "family_liquidity_sweep": float(candidate.family.value == "LIQUIDITY_SWEEP_REVERSAL"),
            "symbol_btc": float(candidate.symbol == "BTCUSDT"),
            "utc_hour_sin": float(np.sin(2 * np.pi * candidate.timestamp.hour / 24)),
            "utc_hour_cos": float(np.cos(2 * np.pi * candidate.timestamp.hour / 24)),
        }
    )
    return {name: values.get(name, np.nan) for name in FEATURE_COLUMNS}


def _quality_eligible(candidate: Any, gate: FrozenQualityGate) -> bool:
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


def _fit_models(
    labels_path: Path,
    training_cutoff: pd.Timestamp,
    config: FrozenActionModel,
) -> tuple[HistGradientBoostingRegressor, HistGradientBoostingRegressor, pd.DataFrame]:
    labels = pd.read_pickle(labels_path, compression="gzip")
    labels["event_end"] = pd.to_datetime(labels["event_end"], utc=True)
    labels = _budget_targets(labels)
    labels = labels[
        (labels["event_end"] < training_cutoff)
        & labels["market_budget_r"].notna()
        & labels["passive_budget_r"].notna()
    ].copy()
    if len(labels) < 500:
        raise RuntimeError(f"insufficient pre-period training rows: {len(labels)}")
    x = labels.reindex(columns=FEATURE_COLUMNS).replace([np.inf, -np.inf], np.nan)
    kwargs = dict(
        max_leaf_nodes=config.max_leaf_nodes,
        min_samples_leaf=config.min_samples_leaf,
        max_iter=config.max_iter,
        learning_rate=config.learning_rate,
        l2_regularization=config.l2_regularization,
        random_state=config.random_state,
    )
    market_model = HistGradientBoostingRegressor(**kwargs).fit(x, labels["market_budget_r"].astype(float))
    passive_model = HistGradientBoostingRegressor(**kwargs).fit(x, labels["passive_budget_r"].astype(float))
    return market_model, passive_model, labels


def _score_candidates(
    candidates: Sequence[Any],
    market_model: HistGradientBoostingRegressor,
    passive_model: HistGradientBoostingRegressor,
    model_config: FrozenActionModel,
) -> tuple[list[ScoredCandidate], list[dict[str, Any]], Counter[str]]:
    if not candidates:
        return [], [], Counter()
    x = pd.DataFrame([_candidate_features(candidate) for candidate in candidates], columns=FEATURE_COLUMNS)
    x = x.replace([np.inf, -np.inf], np.nan)
    predicted_market = market_model.predict(x)
    predicted_passive = passive_model.predict(x)
    scored: list[ScoredCandidate] = []
    rows: list[dict[str, Any]] = []
    actions: Counter[str] = Counter()
    for candidate, market_prediction, passive_prediction in zip(
        candidates, predicted_market, predicted_passive, strict=True
    ):
        market_score = float(market_prediction - model_config.threshold_budget_r)
        passive_score = float(passive_prediction - model_config.threshold_budget_r)
        best_score = max(market_score, passive_score)
        preferred = "PASSIVE_RETEST" if passive_score >= market_score else "MARKETABLE"
        if best_score > 0:
            actions[preferred] += 1
        scored.append(
            ScoredCandidate(
                candidate=candidate,
                win_probability=0.5,
                expected_net_r=float(market_prediction),
                passive_fill_probability=1.0,
                expected_log_growth=max(float(market_prediction), float(passive_prediction)),
                lower_confidence_score=best_score,
                passive_win_probability=0.5,
                market_expected_log_growth=float(market_prediction),
                passive_expected_log_growth=float(passive_prediction),
                market_lower_confidence_score=market_score,
                passive_lower_confidence_score=passive_score,
                preferred_action=preferred,
            )
        )
        rows.append(
            {
                "timestamp": candidate.timestamp.isoformat(),
                "symbol": candidate.symbol,
                "family": candidate.family.value,
                "side": candidate.side,
                "entry_reference": candidate.entry_reference,
                "stop_reference": candidate.stop_reference,
                "target_reference": candidate.target_reference,
                "predicted_market_budget_r": float(market_prediction),
                "predicted_passive_budget_r": float(passive_prediction),
                "passes_threshold": bool(best_score > 0),
                "preferred_action": preferred,
            }
        )
    return scored, rows, actions


def _final_mark(
    account: Any,
    execution: dict[str, pd.DataFrame],
    end: pd.Timestamp,
    config: CoarseExecutionConfig,
) -> tuple[float, float | None]:
    final_mark = 0.0
    final_closeout: float | None = None
    if account.position is not None:
        frame = execution[account.position.candidate.symbol]
        eligible = frame.loc[pd.to_datetime(frame["bar_start"], utc=True) < end]
        row = eligible.iloc[-1]
        final_mark = float(row.get("mark_close", row["close"]))
        final_closeout = coarse_closeout_price(row, account.position.side, config)
        return final_mark, final_closeout
    for frame in execution.values():
        eligible = frame.loc[pd.to_datetime(frame["bar_start"], utc=True) < end]
        if not eligible.empty:
            row = eligible.iloc[-1]
            final_mark = float(row.get("mark_close", row["close"]))
    return final_mark, None


def run(args: argparse.Namespace) -> dict[str, Any]:
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end_exclusive)
    gate = FrozenQualityGate()
    model_config = FrozenActionModel()
    account_config = FrozenAccount(args.risk_fraction, args.maximum_leverage, args.initial_nav)

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
                if _quality_eligible(candidate, gate):
                    eligible_candidates.append(candidate)
    eligible_candidates.sort(key=lambda c: (c.timestamp, c.symbol, c.family.value, c.side))

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
        "training_cutoff": start.isoformat(),
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
        "ml_threshold_pass_candidates": int(
            sum(
                max(row["predicted_market_budget_r"], row["predicted_passive_budget_r"])
                >= model_config.threshold_budget_r
                for row in score_rows
            )
        ),
        "predicted_action_counts_before_slot": dict(action_counts),
        "candidate_generation_diagnostics": diagnostics,
        "metrics": metrics.as_dict(),
        "closed_trades": [asdict(trade) for trade in account.closed_trades],
        "daily_nav": [asdict(record) for record in account.daily_nav],
        "candidate_scores": score_rows,
        "ranking_effect": args.ranking_effect,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    result_path = args.output / "FROZEN_PERIOD_RESULT.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (args.output / "FROZEN_PERIOD_RESULT.sha256").write_text(
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
    parser.add_argument("--stage", default="FROZEN_CAUSAL_ML_COARSE_PROVISIONAL")
    parser.add_argument(
        "--scientific-source-sha",
        default="d08e0f7f2aa3ea983cc719a16a1569ad61005bbe",
    )
    parser.add_argument("--training-label-artifact-id", type=int, default=8643192491)
    parser.add_argument("--ranking-effect", default="PROVISIONAL_NOT_EVENT_TAPE_VALIDATED")
    args = parser.parse_args(argv)
    result = run(args)
    print(
        json.dumps(
            {
                "metrics": result["metrics"],
                "quality_eligible_candidates": result["quality_eligible_candidates"],
                "ml_threshold_pass_candidates": result["ml_threshold_pass_candidates"],
                "actions": result["predicted_action_counts_before_slot"],
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
