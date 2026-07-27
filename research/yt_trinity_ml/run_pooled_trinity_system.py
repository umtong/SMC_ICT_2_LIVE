#!/usr/bin/env python3
"""Pool only pre-2024-positive logical families into one global-slot ML system.

Family inclusion, family-specific variant sets, model architecture/update cadence,
risk and leverage are all selected using data whose outcomes are available by
2023-12-31.  H1 is a survival gate, not a magnitude-selection surface.  A
survivor then replays the full 2024-2026 interval on one continuous NAV path.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

import run_cisd_bpr_ifvg_research as engine
import run_compression_bpr_continuation as compression
import run_full_sequential_survivor as full
import run_smt_cisd_research as smt
from system.coarse import CoarseExecutionConfig
from system.core import EventCandidate


ROUTES = {
    "cisd_bpr_ifvg": ("CISD_BPR_IFVG_RUN_POINTER.json", "YT_TRINITY_CISD_BPR_IFVG_ACTION_VALUE_V1"),
    "compression_bpr": ("COMPRESSION_BPR_RUN_POINTER.json", "YT_TRINITY_COMPRESSION_BPR_CONTINUATION_ACTION_VALUE_V1"),
    "smt_cisd": ("SMT_CISD_RUN_POINTER.json", "YT_TRINITY_SMT_CISD_BPR_ACTION_VALUE_V1"),
}


def route_variant(candidate: EventCandidate) -> str:
    if candidate.feature_row.get("variant_bpr"):
        return "BPR"
    if candidate.feature_row.get("variant_ifvg"):
        return "IFVG"
    return "CISD_FVG"


def frozen_positive_routes(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    included: list[dict[str, Any]] = []
    for route_key, (filename, strategy_id) in ROUTES.items():
        path = root / filename
        if not path.exists():
            raise RuntimeError(f"route result missing: {filename}")
        pointer = json.loads(path.read_text(encoding="utf-8"))
        decision = str(pointer.get("decision") or "")
        if decision not in {"ECONOMIC_FAIL_SWITCH_ALPHA", "POSITIVE_PRE2024_OPENED_2024H1_COARSE"}:
            raise RuntimeError(f"route not economically resolved: {route_key} {decision}")
        basic = pointer.get("selected_basic")
        metrics = basic.get("metrics") if isinstance(basic, Mapping) else None
        positive = (
            decision == "POSITIVE_PRE2024_OPENED_2024H1_COARSE"
            and isinstance(metrics, Mapping)
            and float(metrics.get("geometric_daily_growth") or 0.0) > 0.0
            and not bool(metrics.get("liquidated_or_invalid"))
        )
        row = {
            "route_key": route_key,
            "strategy_id": strategy_id,
            "pointer_file": filename,
            "pointer_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "decision": decision,
            "selected_basic": basic,
            "pre2024_positive": positive,
        }
        rows.append(row)
        if positive:
            variant_set = str(basic.get("variant_set") or "")
            if variant_set not in engine.VARIANT_SETS:
                raise RuntimeError(f"invalid frozen variant set for {route_key}: {variant_set}")
            included.append({**row, "variant_set": variant_set})
    return rows, included


def augment(candidate: EventCandidate, route_key: str) -> EventCandidate:
    features = dict(candidate.feature_row)
    features.update(
        {
            "route_cisd_bpr_ifvg": float(route_key == "cisd_bpr_ifvg"),
            "route_compression_bpr": float(route_key == "compression_bpr"),
            "route_smt_cisd": float(route_key == "smt_cisd"),
        }
    )
    return dataclasses.replace(candidate, feature_row=features)


def generate_pooled_candidates(
    decision_frames: Mapping[str, pd.DataFrame],
    included: list[dict[str, Any]],
):
    feature_counts: dict[str, dict[str, int]] = {}
    candidates: list[EventCandidate] = []
    for route in included:
        route_key = route["route_key"]
        allowed = engine.VARIANT_SETS[route["variant_set"]]
        route_candidates: list[EventCandidate] = []
        route_features: dict[str, pd.DataFrame]
        if route_key == "smt_cisd":
            route_features, generated = smt.generate_joint_candidates(decision_frames)
            route_candidates.extend(generated)
        else:
            generator = engine.generate_candidates if route_key == "cisd_bpr_ifvg" else compression.generate_candidates
            route_features = {}
            for symbol in engine.SYMBOLS:
                features, generated = generator(decision_frames[symbol], symbol)
                route_features[symbol] = features
                route_candidates.extend(generated)
        selected = [augment(row, route_key) for row in route_candidates if route_variant(row) in allowed]
        candidates.extend(selected)
        feature_counts[route_key] = {symbol: len(frame) for symbol, frame in route_features.items()}
    candidates.sort(key=lambda row: (row.timestamp, row.symbol, row.side, row.family.value, row.entry_reference))
    return feature_counts, candidates


def pooled_specs() -> tuple[engine.ModelSpec, ...]:
    rows: list[engine.ModelSpec] = []
    for base in engine.MODEL_SPECS:
        rows.append(dataclasses.replace(base, name=f"{base.name}_28D", update_cadence_days=28))
        rows.append(dataclasses.replace(base, name=f"{base.name}_7D", update_cadence_days=7))
    return tuple(rows)


def full_execution_triplet():
    realistic = engine.DEFAULT_EXECUTION
    zero = CoarseExecutionConfig(
        activation_latency_ms=realistic.activation_latency_ms,
        maker_fee_rate=0.0,
        taker_fee_rate=0.0,
        market_slippage_bps=0.0,
        stop_slippage_bps=0.0,
        passive_requires_trade_through=realistic.passive_requires_trade_through,
        minimum_spread_bps=0.0,
    )
    stressed = CoarseExecutionConfig(
        activation_latency_ms=realistic.activation_latency_ms,
        maker_fee_rate=realistic.maker_fee_rate * 1.25,
        taker_fee_rate=realistic.taker_fee_rate * 1.25,
        market_slippage_bps=realistic.market_slippage_bps * 1.5,
        stop_slippage_bps=realistic.stop_slippage_bps * 1.5,
        passive_requires_trade_through=True,
        minimum_spread_bps=max(realistic.minimum_spread_bps * 1.5, 0.75),
    )
    return realistic, zero, stressed


def run(args: argparse.Namespace) -> dict[str, Any]:
    route_rows, included = frozen_positive_routes(args.pointer_root)
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    if not included:
        summary = {
            "schema_version": 1,
            "strategy_id": "YT_TRINITY_PRE2024_POSITIVE_FAMILY_POOL_V1",
            "decision": "NO_PRE2024_POSITIVE_FAMILY_SWITCH_ALPHA",
            "route_results": route_rows,
            "included_routes": [],
            "rankable": False,
        }
        path = args.output / "RUN_SUMMARY.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (args.output / "RUN_SUMMARY.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  RUN_SUMMARY.json\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return summary

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(engine.SYMBOLS)) as pool:
        futures = {
            symbol: pool.submit(engine.fetch_minute_klines, symbol, full.DATA_START, full.OFFICIAL_END, args.cache_dir)
            for symbol in engine.SYMBOLS
        }
        execution_frames = {symbol: future.result() for symbol, future in futures.items()}
    funding: dict[tuple[str, pd.Timestamp], float] = {}
    for symbol in engine.SYMBOLS:
        funding.update(engine.fetch_funding(symbol, full.DATA_START, full.OFFICIAL_END, args.cache_dir))
    decision_frames = {symbol: engine.resample_decision(frame) for symbol, frame in execution_frames.items()}
    feature_counts, candidates = generate_pooled_candidates(decision_frames, included)
    labels = engine.build_action_labels(candidates, execution_frames, engine.DEFAULT_EXECUTION)
    labels_path = args.output / "POOLED_ACTION_LABELS.parquet"
    labels.to_parquet(labels_path, index=False)

    pre2024_start = pd.Timestamp("2023-01-01T00:00:00Z")
    basic_results: list[dict[str, Any]] = []
    prediction_cache: dict[str, tuple[list[engine.PredictionRecord], list[dict[str, Any]]]] = {}
    for spec in pooled_specs():
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
        print(json.dumps({"stage": "pooled_basic", "id": spec.name, "metrics": metrics}, ensure_ascii=False), flush=True)
    selected_basic = max(basic_results, key=lambda row: engine.result_key(row["metrics"]))
    positive_basic = float(selected_basic["metrics"].get("geometric_daily_growth") or 0.0) > 0 and not bool(selected_basic["metrics"].get("liquidated_or_invalid"))
    risk_results: list[dict[str, Any]] = []
    selected_risk = None
    h1_result = None
    full_result = None
    final_decision = "ECONOMIC_FAIL_SWITCH_ALPHA"
    if positive_basic:
        spec = engine.ModelSpec(**selected_basic["model_spec"])
        pre_predictions, _ = prediction_cache[spec.name]
        for risk_fraction in (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.20):
            for leverage in (2.0, 5.0, 10.0, 20.0, 50.0, 100.0):
                metrics, _ = engine.replay_predictions(
                    pre_predictions,
                    execution_frames,
                    funding,
                    pre2024_start,
                    full.OFFICIAL_START,
                    risk_fraction=risk_fraction,
                    maximum_leverage=leverage,
                    confidence_penalty=spec.confidence_penalty,
                )
                risk_results.append({
                    "identifier": f"RISK_{risk_fraction:.4f}_LEV_{leverage:.0f}",
                    "risk_fraction": risk_fraction,
                    "maximum_leverage": leverage,
                    "metrics": metrics,
                })
        selected_risk = max(risk_results, key=lambda row: engine.result_key(row["metrics"]))
        h1_end = pd.Timestamp("2024-07-01T00:00:00Z")
        h1_predictions, h1_ledger = engine.walk_forward_predictions(
            candidates,
            labels,
            full.OFFICIAL_START,
            h1_end,
            spec,
            engine.VARIANT_SETS["ALL_CAUSAL_ZONES"],
        )
        h1_metrics, h1_account = engine.replay_predictions(
            h1_predictions,
            execution_frames,
            funding,
            full.OFFICIAL_START,
            h1_end,
            risk_fraction=float(selected_risk["risk_fraction"]),
            maximum_leverage=float(selected_risk["maximum_leverage"]),
            confidence_penalty=spec.confidence_penalty,
        )
        h1_result = {
            "metrics": h1_metrics,
            "prediction_count": len(h1_predictions),
            "update_records": h1_ledger,
            "closed_trade_count": len(h1_account.closed_trades),
        }
        h1_positive = (
            float(h1_metrics.get("geometric_daily_growth") or 0.0) > 0
            and float(h1_metrics.get("account_multiple") or 0.0) > 1.0
            and not bool(h1_metrics.get("liquidated_or_invalid"))
        )
        if h1_positive:
            official_predictions, official_ledger = engine.walk_forward_predictions(
                candidates,
                labels,
                full.OFFICIAL_START,
                full.OFFICIAL_END,
                spec,
                engine.VARIANT_SETS["ALL_CAUSAL_ZONES"],
            )
            realistic_config, zero_config, stressed_config = full_execution_triplet()
            realistic_metrics, realistic_account = full.replay_with_contract(
                official_predictions, execution_frames, funding,
                float(selected_risk["risk_fraction"]), float(selected_risk["maximum_leverage"]),
                spec.confidence_penalty, realistic_config,
            )
            zero_metrics, _ = full.replay_with_contract(
                official_predictions, execution_frames, funding,
                float(selected_risk["risk_fraction"]), float(selected_risk["maximum_leverage"]),
                spec.confidence_penalty, zero_config,
            )
            stressed_metrics, _ = full.replay_with_contract(
                official_predictions, execution_frames, funding,
                float(selected_risk["risk_fraction"]), float(selected_risk["maximum_leverage"]),
                spec.confidence_penalty, stressed_config,
            )
            daily_rows = full.object_rows(realistic_account.daily_nav)
            trade_rows = full.object_rows(realistic_account.closed_trades)
            fill_rows = full.object_rows(realistic_account.fills)
            daily_sha = full.write_jsonl(args.output / "DAILY_NAV.jsonl", daily_rows)
            trade_sha = full.write_jsonl(args.output / "CLOSED_TRADES.jsonl", trade_rows)
            fill_sha = full.write_jsonl(args.output / "FILLS.jsonl", fill_rows)
            realistic_growth = float(realistic_metrics.get("geometric_daily_growth") or -1.0)
            zero_growth = float(zero_metrics.get("geometric_daily_growth") or -1.0)
            invalid = bool(realistic_metrics.get("liquidated_or_invalid"))
            if not invalid and realistic_growth >= full.TARGET_DAILY_GROWTH:
                final_decision = "TARGET_EXCEEDED_COARSE_EVENT_TAPE_REQUIRED"
            elif not invalid and zero_growth >= full.TARGET_DAILY_GROWTH:
                final_decision = "TARGET_POSSIBLE_ONLY_WITH_EXECUTION_EDGE_EVENT_TAPE_REQUIRED"
            elif not invalid and realistic_growth > 0:
                final_decision = "POSITIVE_BUT_ZERO_COST_BELOW_TARGET_SWITCH_ALPHA"
            else:
                final_decision = "OFFICIAL_FULL_PERIOD_ECONOMIC_FAIL_SWITCH_ALPHA"
            full_result = {
                "realistic_execution": dataclasses.asdict(realistic_config),
                "realistic_metrics": realistic_metrics,
                "zero_friction_execution": dataclasses.asdict(zero_config),
                "zero_friction_metrics_same_signals": zero_metrics,
                "stressed_execution": dataclasses.asdict(stressed_config),
                "stressed_metrics_same_signals": stressed_metrics,
                "prediction_count": len(official_predictions),
                "update_records": official_ledger,
                "half_years": full.half_year_summary(realistic_account),
                "evidence": {
                    "daily_nav_sha256": daily_sha,
                    "closed_trades_sha256": trade_sha,
                    "fills_sha256": fill_sha,
                    "daily_nav_rows": len(daily_rows),
                    "closed_trade_rows": len(trade_rows),
                    "fill_rows": len(fill_rows),
                },
            }
        else:
            final_decision = "H1_STRUCTURALLY_WEAK_SWITCH_ALPHA"

    summary = {
        "schema_version": 1,
        "strategy_id": "YT_TRINITY_PRE2024_POSITIVE_FAMILY_POOL_V1",
        "stage": "PRE2024_SELECTED_AND_CONDITIONAL_FULL_CAUSAL_COARSE_NOT_RANKABLE",
        "route_results": route_rows,
        "included_routes": included,
        "feature_row_counts": feature_counts,
        "candidate_count": len(candidates),
        "action_label_count": len(labels),
        "action_label_sha256": engine.sha256_file(labels_path),
        "basic_results": basic_results,
        "selected_basic": selected_basic,
        "pre2024_positive_basic_alpha": positive_basic,
        "risk_results": risk_results,
        "selected_risk": selected_risk,
        "official_2024h1": h1_result,
        "official_full_period": full_result,
        "decision": final_decision,
        "rankable": False,
        "rankability_blockers": [
            "sub-minute event-tape replay remains required for any positive survivor",
            "complete three-channel content corpus and audited ontology binding remains required",
        ],
    }
    path = args.output / "RUN_SUMMARY.json"
    path.write_text(json.dumps(full.jsonable(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "RUN_SUMMARY.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  RUN_SUMMARY.json\n", encoding="utf-8")
    print(json.dumps(full.jsonable(summary), ensure_ascii=False, indent=2, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pointer-root", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
