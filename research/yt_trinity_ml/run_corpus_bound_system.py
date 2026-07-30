#!/usr/bin/env python3
"""Run the frozen corpus-bound pooled action-value system.

The corpus contract decides which logical families are eligible and fixes the
selection procedure.  This runner generates only those families, selects model
and risk exclusively on pre-2024 sequential after-cost NAV, writes and hashes the
frozen configuration, then opens one continuous 2024-2026 account.  Official
returns never feed back into configuration selection.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

import run_cisd_bpr_ifvg_research as engine
import run_compression_bpr_continuation as compression
import run_full_sequential_survivor as full
import run_htf_ote_continuation as htf_ote
import run_ifvg_failure_research as ifvg_failure
import run_smt_cisd_research as smt
from system.core import EventCandidate


ROUTE_GENERATORS = {
    "cisd_bpr_ifvg": "single",
    "compression_bpr": "single",
    "smt_cisd": "joint",
    "ifvg_failure": "single",
    "htf_ote": "single",
}


def route_variant(candidate: EventCandidate) -> str:
    if candidate.feature_row.get("variant_bpr"):
        return "BPR"
    if candidate.feature_row.get("variant_ifvg"):
        return "IFVG"
    return "CISD_FVG"


def contract_route(contract: Mapping[str, Any], route_key: str) -> Mapping[str, Any]:
    table = contract.get("route_pre2024_evidence")
    if not isinstance(table, Mapping) or not isinstance(table.get(route_key), Mapping):
        raise RuntimeError(f"contract lacks pre-2024 route evidence: {route_key}")
    return table[route_key]


def allowed_variants(contract: Mapping[str, Any], route_key: str) -> frozenset[str]:
    row = contract_route(contract, route_key)
    selected = row.get("selected_basic_pre2024_only")
    variant_set = selected.get("variant_set") if isinstance(selected, Mapping) else None
    if variant_set not in engine.VARIANT_SETS:
        raise RuntimeError(f"invalid frozen variant set for {route_key}: {variant_set}")
    return engine.VARIANT_SETS[str(variant_set)]


def augment(candidate: EventCandidate, route_key: str, eligible: list[str]) -> EventCandidate:
    features = dict(candidate.feature_row)
    for key in ROUTE_GENERATORS:
        features[f"route_{key}"] = float(key == route_key)
    features["corpus_bound_family_count"] = float(len(eligible))
    return dataclasses.replace(candidate, feature_row=features)


def generate_candidates(
    contract: Mapping[str, Any],
    decision_frames: Mapping[str, pd.DataFrame],
) -> tuple[dict[str, dict[str, int]], list[EventCandidate], dict[str, int]]:
    eligible = [str(value) for value in contract.get("eligible_family_keys") or []]
    if not eligible:
        raise RuntimeError("corpus contract has no eligible families")
    unknown = sorted(set(eligible) - set(ROUTE_GENERATORS))
    if unknown:
        raise RuntimeError(f"unknown corpus-bound routes: {unknown}")
    feature_counts: dict[str, dict[str, int]] = {}
    candidate_counts: dict[str, int] = {}
    pooled: list[EventCandidate] = []
    for route_key in eligible:
        variants = allowed_variants(contract, route_key)
        route_rows: list[EventCandidate] = []
        route_features: dict[str, pd.DataFrame]
        if route_key == "smt_cisd":
            route_features, generated = smt.generate_joint_candidates(decision_frames)
            route_rows.extend(generated)
        else:
            if route_key == "cisd_bpr_ifvg":
                generator = engine.generate_candidates
            elif route_key == "compression_bpr":
                generator = compression.generate_candidates
            elif route_key == "ifvg_failure":
                generator = ifvg_failure.generate_candidates
            else:
                generator = htf_ote.generate_candidates
            route_features = {}
            for symbol in engine.SYMBOLS:
                features, generated = generator(decision_frames[symbol], symbol)
                route_features[symbol] = features
                route_rows.extend(generated)
        selected = [
            augment(row, route_key, eligible)
            for row in route_rows
            if route_variant(row) in variants
        ]
        pooled.extend(selected)
        candidate_counts[route_key] = len(selected)
        feature_counts[route_key] = {
            symbol: len(frame) for symbol, frame in route_features.items()
        }
    pooled.sort(
        key=lambda row: (
            row.timestamp,
            row.symbol,
            row.side,
            row.family.value,
            row.entry_reference,
        )
    )
    return feature_counts, pooled, candidate_counts


def model_specs() -> tuple[engine.ModelSpec, ...]:
    rows: list[engine.ModelSpec] = []
    for base in engine.MODEL_SPECS:
        rows.append(
            dataclasses.replace(
                base,
                name=f"{base.name}_28D",
                update_cadence_days=28,
                activation_lag_minutes=15,
            )
        )
        rows.append(
            dataclasses.replace(
                base,
                name=f"{base.name}_7D",
                update_cadence_days=7,
                activation_lag_minutes=15,
            )
        )
    return tuple(rows)


def scored_rows(predictions, risk_fraction: float, confidence_penalty: float):
    rows = []
    for scored in engine.score_predictions(
        predictions, risk_fraction, confidence_penalty
    ):
        candidate = scored.candidate
        rows.append(
            {
                "timestamp": candidate.timestamp,
                "symbol": candidate.symbol,
                "family": candidate.family.value,
                "side": candidate.side,
                "decision_price": candidate.decision_price,
                "entry_reference": candidate.entry_reference,
                "stop_reference": candidate.stop_reference,
                "target_reference": candidate.target_reference,
                "structural_level": candidate.structural_level,
                "feature_row": dict(candidate.feature_row),
                "win_probability": scored.win_probability,
                "expected_net_r": scored.expected_net_r,
                "passive_fill_probability": scored.passive_fill_probability,
                "expected_log_growth": scored.expected_log_growth,
                "lower_confidence_score": scored.lower_confidence_score,
                "chosen_action": scored.chosen_action.value,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    if (
        contract.get("decision") != "CORPUS_BOUND_PRE2024_SELECTION_READY"
        or contract.get("status") != "FROZEN"
    ):
        raise RuntimeError(
            f"corpus contract is not ready: {contract.get('decision')}"
        )

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(engine.SYMBOLS)
    ) as pool:
        futures = {
            symbol: pool.submit(
                engine.fetch_minute_klines,
                symbol,
                full.DATA_START,
                full.OFFICIAL_END,
                args.cache_dir,
            )
            for symbol in engine.SYMBOLS
        }
        execution_frames = {
            symbol: future.result() for symbol, future in futures.items()
        }
    funding: dict[tuple[str, pd.Timestamp], float] = {}
    for symbol in engine.SYMBOLS:
        funding.update(
            engine.fetch_funding(
                symbol, full.DATA_START, full.OFFICIAL_END, args.cache_dir
            )
        )
    decision_frames = {
        symbol: engine.resample_decision(frame)
        for symbol, frame in execution_frames.items()
    }
    feature_counts, candidates, family_candidate_counts = generate_candidates(
        contract, decision_frames
    )
    labels = engine.build_action_labels(
        candidates, execution_frames, engine.DEFAULT_EXECUTION
    )
    labels_path = args.output / "CORPUS_BOUND_ACTION_LABELS.parquet"
    labels.to_parquet(labels_path, index=False)

    pre2024_start = pd.Timestamp("2023-01-01T00:00:00Z")
    basic_results: list[dict[str, Any]] = []
    prediction_cache: dict[
        str, tuple[list[engine.PredictionRecord], list[dict[str, Any]]]
    ] = {}
    for spec in model_specs():
        predictions, ledger = engine.walk_forward_predictions(
            candidates,
            labels,
            pre2024_start,
            full.OFFICIAL_START,
            spec,
            engine.VARIANT_SETS["ALL_CAUSAL_ZONES"],
        )
        prediction_cache[spec.name] = (predictions, ledger)
        metrics, _ = engine.replay_predictions(
            predictions,
            execution_frames,
            funding,
            pre2024_start,
            full.OFFICIAL_START,
            risk_fraction=0.01,
            maximum_leverage=5.0,
            confidence_penalty=spec.confidence_penalty,
        )
        result = {
            "identifier": spec.name,
            "model_spec": dataclasses.asdict(spec),
            "prediction_count": len(predictions),
            "update_records": ledger,
            "metrics": metrics,
        }
        basic_results.append(result)
        print(
            json.dumps(
                {
                    "stage": "corpus_bound_basic",
                    "id": spec.name,
                    "metrics": metrics,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    if not basic_results:
        raise RuntimeError("no model results")
    selected_basic = max(
        basic_results, key=lambda row: engine.result_key(row["metrics"])
    )
    positive_basic = (
        float(
            selected_basic["metrics"].get("geometric_daily_growth") or 0.0
        )
        > 0
        and not bool(
            selected_basic["metrics"].get("liquidated_or_invalid")
        )
    )
    if not positive_basic:
        summary = {
            "schema_version": 1,
            "strategy_id": contract["system_id"],
            "stage": "CORPUS_BOUND_PRE2024_CAUSAL_COARSE_NOT_RANKABLE",
            "contract_sha256": hashlib.sha256(
                args.contract.read_bytes()
            ).hexdigest(),
            "eligible_family_keys": contract["eligible_family_keys"],
            "family_candidate_counts": family_candidate_counts,
            "candidate_count": len(candidates),
            "action_label_count": len(labels),
            "action_label_sha256": hashlib.sha256(
                labels_path.read_bytes()
            ).hexdigest(),
            "basic_results": basic_results,
            "selected_basic": selected_basic,
            "pre2024_positive_basic_alpha": False,
            "decision": "CORPUS_BOUND_POOLED_PRE2024_ECONOMIC_FAIL_SWITCH_ALPHA",
            "official_period_opened": False,
            "rankable": False,
        }
        path = args.output / "RUN_SUMMARY.json"
        path.write_text(
            json.dumps(
                full.jsonable(summary),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (args.output / "RUN_SUMMARY.sha256").write_text(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  RUN_SUMMARY.json\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                full.jsonable(summary),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    spec = engine.ModelSpec(**selected_basic["model_spec"])
    pre_predictions, _ = prediction_cache[spec.name]
    risk_results: list[dict[str, Any]] = []
    for risk_fraction in (
        0.0025,
        0.005,
        0.01,
        0.02,
        0.04,
        0.08,
        0.12,
        0.20,
    ):
        for maximum_leverage in (2.0, 5.0, 10.0, 20.0, 50.0, 100.0):
            metrics, _ = engine.replay_predictions(
                pre_predictions,
                execution_frames,
                funding,
                pre2024_start,
                full.OFFICIAL_START,
                risk_fraction=risk_fraction,
                maximum_leverage=maximum_leverage,
                confidence_penalty=spec.confidence_penalty,
            )
            risk_results.append(
                {
                    "identifier": f"RISK_{risk_fraction:.4f}_LEV_{maximum_leverage:.0f}",
                    "risk_fraction": risk_fraction,
                    "maximum_leverage": maximum_leverage,
                    "metrics": metrics,
                }
            )
    selected_risk = max(
        risk_results, key=lambda row: engine.result_key(row["metrics"])
    )
    frozen_config = {
        "schema_version": 1,
        "system_id": contract["system_id"],
        "contract_sha256": hashlib.sha256(
            args.contract.read_bytes()
        ).hexdigest(),
        "corpus_binding": contract["corpus_binding"],
        "eligible_family_keys": contract["eligible_family_keys"],
        "family_variant_sets": {
            route: contract_route(contract, route)[
                "selected_basic_pre2024_only"
            ]["variant_set"]
            for route in contract["eligible_family_keys"]
        },
        "pooled_model_spec": dataclasses.asdict(spec),
        "risk_fraction": selected_risk["risk_fraction"],
        "maximum_leverage": selected_risk["maximum_leverage"],
        "execution_config": dataclasses.asdict(engine.DEFAULT_EXECUTION),
        "training_selection_end_exclusive": full.OFFICIAL_START.isoformat(),
        "official_start": full.OFFICIAL_START.isoformat(),
        "official_end_exclusive": full.OFFICIAL_END.isoformat(),
        "official_period_fields_used_for_selection": False,
    }
    frozen_path = args.output / "FROZEN_CONFIG.json"
    frozen_raw = (
        json.dumps(
            full.jsonable(frozen_config),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    frozen_path.write_text(frozen_raw, encoding="utf-8")
    frozen_sha = hashlib.sha256(frozen_raw.encode("utf-8")).hexdigest()
    (args.output / "FROZEN_CONFIG.sha256").write_text(
        f"{frozen_sha}  FROZEN_CONFIG.json\n", encoding="utf-8"
    )

    official_predictions, official_ledger = engine.walk_forward_predictions(
        candidates,
        labels,
        full.OFFICIAL_START,
        full.OFFICIAL_END,
        spec,
        engine.VARIANT_SETS["ALL_CAUSAL_ZONES"],
    )
    scored = scored_rows(
        official_predictions,
        float(selected_risk["risk_fraction"]),
        spec.confidence_penalty,
    )
    scored_sha = full.write_jsonl(
        args.output / "SCORED_CANDIDATES.jsonl", scored
    )
    realistic_config, zero_config, stressed_config = (
        engine.DEFAULT_EXECUTION,
        dataclasses.replace(
            engine.DEFAULT_EXECUTION,
            maker_fee_rate=0.0,
            taker_fee_rate=0.0,
            market_slippage_bps=0.0,
            stop_slippage_bps=0.0,
            minimum_spread_bps=0.0,
        ),
        dataclasses.replace(
            engine.DEFAULT_EXECUTION,
            maker_fee_rate=engine.DEFAULT_EXECUTION.maker_fee_rate * 1.25,
            taker_fee_rate=engine.DEFAULT_EXECUTION.taker_fee_rate * 1.25,
            market_slippage_bps=engine.DEFAULT_EXECUTION.market_slippage_bps
            * 1.5,
            stop_slippage_bps=engine.DEFAULT_EXECUTION.stop_slippage_bps
            * 1.5,
            minimum_spread_bps=max(
                engine.DEFAULT_EXECUTION.minimum_spread_bps * 1.5, 0.75
            ),
        ),
    )
    realistic_metrics, realistic_account = full.replay_with_contract(
        official_predictions,
        execution_frames,
        funding,
        float(selected_risk["risk_fraction"]),
        float(selected_risk["maximum_leverage"]),
        spec.confidence_penalty,
        realistic_config,
    )
    zero_metrics, _ = full.replay_with_contract(
        official_predictions,
        execution_frames,
        funding,
        float(selected_risk["risk_fraction"]),
        float(selected_risk["maximum_leverage"]),
        spec.confidence_penalty,
        zero_config,
    )
    stressed_metrics, _ = full.replay_with_contract(
        official_predictions,
        execution_frames,
        funding,
        float(selected_risk["risk_fraction"]),
        float(selected_risk["maximum_leverage"]),
        spec.confidence_penalty,
        stressed_config,
    )
    daily_rows = full.object_rows(realistic_account.daily_nav)
    trade_rows = full.object_rows(realistic_account.closed_trades)
    fill_rows = full.object_rows(realistic_account.fills)
    daily_sha = full.write_jsonl(args.output / "DAILY_NAV.jsonl", daily_rows)
    trade_sha = full.write_jsonl(
        args.output / "CLOSED_TRADES.jsonl", trade_rows
    )
    fill_sha = full.write_jsonl(args.output / "FILLS.jsonl", fill_rows)
    realistic_growth = float(
        realistic_metrics.get("geometric_daily_growth") or -1.0
    )
    zero_growth = float(
        zero_metrics.get("geometric_daily_growth") or -1.0
    )
    invalid = bool(realistic_metrics.get("liquidated_or_invalid"))
    if not invalid and realistic_growth >= full.TARGET_DAILY_GROWTH:
        decision = "TARGET_EXCEEDED_CORPUS_BOUND_COARSE_EVENT_TAPE_REQUIRED"
    elif not invalid and zero_growth >= full.TARGET_DAILY_GROWTH:
        decision = "TARGET_POSSIBLE_ONLY_WITH_CORPUS_BOUND_EXECUTION_EDGE"
    elif not invalid and realistic_growth > 0:
        decision = "CORPUS_BOUND_POSITIVE_BELOW_TARGET_SWITCH_ALPHA"
    else:
        decision = "CORPUS_BOUND_FULL_PERIOD_ECONOMIC_FAIL_SWITCH_ALPHA"
    half_years = full.half_year_summary(realistic_account)
    summary = {
        "schema_version": 1,
        "strategy_id": contract["system_id"],
        "stage": "CORPUS_BOUND_FULL_2024_2026_CAUSAL_COARSE_NOT_RANKABLE",
        "contract_sha256": hashlib.sha256(
            args.contract.read_bytes()
        ).hexdigest(),
        "frozen_config_sha256": frozen_sha,
        "corpus_binding": contract["corpus_binding"],
        "eligible_family_keys": contract["eligible_family_keys"],
        "feature_row_counts": feature_counts,
        "family_candidate_counts": family_candidate_counts,
        "candidate_count": len(candidates),
        "action_label_count": len(labels),
        "action_label_sha256": hashlib.sha256(
            labels_path.read_bytes()
        ).hexdigest(),
        "basic_results": basic_results,
        "selected_basic": selected_basic,
        "risk_results": risk_results,
        "selected_risk": selected_risk,
        "official_period": {
            "start": full.OFFICIAL_START,
            "end_exclusive": full.OFFICIAL_END,
            "initial_nav": 10000.0,
            "continuous_nav_no_resets": True,
        },
        "prediction_count": len(official_predictions),
        "update_records": official_ledger,
        "realistic_execution": dataclasses.asdict(realistic_config),
        "realistic_metrics": realistic_metrics,
        "zero_friction_execution": dataclasses.asdict(zero_config),
        "zero_friction_metrics_same_signals": zero_metrics,
        "stressed_execution": dataclasses.asdict(stressed_config),
        "stressed_metrics_same_signals": stressed_metrics,
        "half_years": half_years,
        "evidence": {
            "scored_candidates_sha256": scored_sha,
            "scored_candidate_rows": len(scored),
            "daily_nav_sha256": daily_sha,
            "daily_nav_rows": len(daily_rows),
            "closed_trades_sha256": trade_sha,
            "closed_trade_rows": len(trade_rows),
            "fills_sha256": fill_sha,
            "fill_rows": len(fill_rows),
        },
        "decision": decision,
        "official_period_fields_used_for_selection": False,
        "rankable": False,
        "rankability_blockers": [
            "exact frozen scored candidates require sub-minute public trade-tape and quote/depth validation"
        ],
    }
    path = args.output / "RUN_SUMMARY.json"
    path.write_text(
        json.dumps(
            full.jsonable(summary),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.output / "RUN_SUMMARY.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  RUN_SUMMARY.json\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            full.jsonable(summary),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
