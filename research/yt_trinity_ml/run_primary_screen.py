#!/usr/bin/env python3
"""Run a causal pre-2024 screen for the unified SMC/ICT narrative.

A weak result no longer routes directly to an unrelated payoff mechanism.  The run
first reports the implementation funnel from knowable liquidity through displacement,
PD-array mitigation, CISD/rejection, labels and account realization.  Reversal and
continuation are terminal delivery modes inside one narrative and have no independent
selection authority.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from run_research import (
    PRIMARY,
    basic_configurations,
    load_canonical_frames,
    load_instrument_rules,
    sha256_file,
    verify_corpus,
)
from system.coarse import CoarseExecutionConfig
from system.core import EventCandidate, EventFamily, FeatureConfig
from system.corpus_alpha import build_corpus_features, generate_corpus_candidates_with_diagnostics
from system.research_pipeline import (
    Pre2024Decision,
    label_event_dataset,
    select_pre2024,
    write_decision,
)


def _finite_stats(values: pd.Series) -> dict[str, float | int | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if numeric.empty:
        return {"count": 0, "mean": None, "median": None, "sum": None, "positive_fraction": None}
    return {
        "count": int(len(numeric)),
        "mean": float(numeric.mean()),
        "median": float(numeric.median()),
        "sum": float(numeric.sum()),
        "positive_fraction": float((numeric > 0).mean()),
        "p10": float(numeric.quantile(0.10)),
        "p90": float(numeric.quantile(0.90)),
    }


def _label_economics(labels: pd.DataFrame) -> dict[str, Any]:
    if labels.empty:
        return {"rows": 0}
    result: dict[str, Any] = {
        "rows": int(len(labels)),
        "market_net_r": _finite_stats(labels["market_net_r"]),
        "market_target_rate": float(pd.to_numeric(labels["market_target_before_stop"], errors="coerce").mean()),
        "passive_fill_rate": float(pd.to_numeric(labels["passive_filled"], errors="coerce").mean()),
        "passive_net_r_including_nonfill_zero": _finite_stats(labels["passive_net_r"]),
        "market_status_counts": dict(sorted(Counter(labels["market_status"].astype(str)).items())),
        "passive_status_counts": dict(sorted(Counter(labels["passive_status"].astype(str)).items())),
    }
    filled = labels[pd.to_numeric(labels["passive_filled"], errors="coerce").eq(1)]
    result["passive_net_r_given_fill"] = (
        _finite_stats(filled["passive_net_r"]) if not filled.empty else _finite_stats(pd.Series(dtype=float))
    )
    result["passive_target_rate_given_fill"] = (
        float(pd.to_numeric(filled["passive_target_before_stop"], errors="coerce").mean())
        if not filled.empty
        else None
    )
    return result


def _candidate_summary(candidates: Sequence[EventCandidate]) -> dict[str, Any]:
    if not candidates:
        return {"count": 0}
    rr = pd.Series(
        [candidate.target_distance / max(candidate.stop_distance, 1e-12) for candidate in candidates],
        dtype=float,
    )
    return {
        "count": int(len(candidates)),
        "by_symbol": dict(sorted(Counter(candidate.symbol for candidate in candidates).items())),
        "by_delivery_mode": dict(sorted(Counter(candidate.family.value for candidate in candidates).items())),
        "by_side": dict(sorted(Counter(str(candidate.side) for candidate in candidates).items())),
        "raw_structural_reward_risk": _finite_stats(rr),
        "first_timestamp": min(candidate.timestamp for candidate in candidates).isoformat(),
        "last_timestamp": max(candidate.timestamp for candidate in candidates).isoformat(),
    }


def _scope_rows(labels: pd.DataFrame, family: EventFamily | None) -> pd.DataFrame:
    if family is None or labels.empty:
        return labels.copy()
    return labels[labels["family"].eq(family.value)].copy()


def _aggregate_diagnostics(by_symbol: Mapping[str, Mapping[str, int]]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for values in by_symbol.values():
        total.update({key: int(value) for key, value in values.items()})
    return dict(sorted(total.items()))


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return float(numerator / denominator) if denominator > 0 else None


def _implementation_audit(
    diagnostics: Mapping[str, int],
    candidate_count: int,
    resolved_labels: int,
    decision: Pre2024Decision,
) -> dict[str, Any]:
    raids = int(diagnostics.get("external_liquidity_raids", 0))
    reversal_armed = int(diagnostics.get("reversal_narratives_armed", 0))
    first_breaks = int(diagnostics.get("continuation_first_break_displacements", 0))
    continuation_armed = int(diagnostics.get("continuation_narratives_armed", 0))
    displacement = int(diagnostics.get("displacement_structure_confirmations", 0))
    pd_arrays = int(diagnostics.get("pd_array_states_armed", 0))
    mitigations = int(diagnostics.get("pd_array_first_mitigations", 0))
    confirmations = int(diagnostics.get("entry_confirmations", 0))

    missing_stages: list[str] = []
    if raids == 0 and first_breaks == 0:
        missing_stages.append("knowable_external_liquidity_or_first_structure_break_detection")
    if raids > 0 and reversal_armed == 0:
        missing_stages.append("raid_to_internal_structure_and_opposing_draw_binding")
    if first_breaks > 0 and continuation_armed == 0:
        missing_stages.append("break_displacement_to_external_draw_and_pd_array_binding")
    if (reversal_armed + continuation_armed) > 0 and displacement == 0:
        missing_stages.append("close_confirmed_displacement_or_market_structure_shift")
    if displacement > 0 and pd_arrays == 0:
        missing_stages.append("displacement_origin_fvg_order_block_construction")
    if pd_arrays > 0 and mitigations == 0:
        missing_stages.append("causal_first_mitigation_detection")
    if mitigations > 0 and confirmations == 0:
        missing_stages.append("post_mitigation_cisd_or_rejection_confirmation")
    if candidate_count > 0 and resolved_labels == 0:
        missing_stages.append("execution_label_resolution")

    selected_growth = (
        None
        if decision.selected is None
        else float(decision.selected.metrics.geometric_daily_growth)
    )
    implementation_complete = candidate_count > 0 and resolved_labels > 0 and not missing_stages
    if selected_growth is not None and selected_growth > 0:
        disposition = "KEEP_UNIFIED_SMC_NARRATIVE_ADVANCE_EXECUTION_VALIDATION"
    elif not implementation_complete:
        disposition = "KEEP_UNIFIED_SMC_NARRATIVE_REPAIR_FIRST_MISSING_STAGE"
    else:
        disposition = "KEEP_UNIFIED_SMC_NARRATIVE_AUDIT_GEOMETRY_LABELS_AND_ML_POLICY"

    return {
        "principle": (
            "A weak account result is not sufficient evidence that the SMC/ICT premise failed. "
            "First separate missing narrative stages, target/stop geometry, label realism, and ML abstention errors."
        ),
        "stage_counts": dict(sorted((str(key), int(value)) for key, value in diagnostics.items())),
        "stage_conversion_ratios": {
            "raid_to_reversal_narrative": _safe_ratio(reversal_armed, raids),
            "first_break_to_continuation_narrative": _safe_ratio(continuation_armed, first_breaks),
            "displacement_to_pd_array": _safe_ratio(pd_arrays, displacement),
            "pd_array_to_first_mitigation": _safe_ratio(mitigations, pd_arrays),
            "mitigation_to_entry_confirmation": _safe_ratio(confirmations, mitigations),
            "candidate_to_resolved_label": _safe_ratio(resolved_labels, candidate_count),
        },
        "missing_or_blocked_stages": missing_stages,
        "implementation_complete_enough_for_economic_judgment": implementation_complete,
        "selected_geometric_daily_growth": selected_growth,
        "disposition": disposition,
        "unrelated_alpha_switch_authorized": False,
        "repair_order": [
            "liquidity pool freshness and draw-on-liquidity binding",
            "raid/BOS to protected internal swing and displacement sequencing",
            "displacement-origin FVG/order-block selection and premium-discount location",
            "mitigation persistence and post-touch CISD/rejection",
            "frozen structural stop/target geometry",
            "action-specific labels, costs, fills and ML abstention policy",
        ],
    }


def run(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    corpus_binding = verify_corpus(args.corpus)
    rules = load_instrument_rules(args.instrument_rules, PRIMARY)
    decision_frames, execution_frames, funding = load_canonical_frames(
        args.data_root,
        args.repo_root,
        PRIMARY,
        args.segments,
    )

    features: dict[str, pd.DataFrame] = {}
    candidates: list[EventCandidate] = []
    diagnostics_by_symbol: dict[str, dict[str, int]] = {}
    for symbol, frame in sorted(decision_frames.items()):
        calculated = build_corpus_features(frame, FeatureConfig())
        symbol_candidates, symbol_diagnostics = generate_corpus_candidates_with_diagnostics(calculated, symbol)
        features[symbol] = calculated
        candidates.extend(symbol_candidates)
        diagnostics_by_symbol[symbol] = symbol_diagnostics
    candidates.sort(key=lambda item: (item.timestamp, item.symbol, item.family.value, item.side))

    labels = label_event_dataset(candidates, execution_frames, CoarseExecutionConfig())
    label_path = args.output / "EVENT_LABELS.parquet"
    labels.to_parquet(label_path, index=False)

    validation_start = pd.Timestamp(args.validation_start)
    validation_end = pd.Timestamp(args.validation_end_exclusive)
    decision = select_pre2024(
        basic_configurations(rules),
        candidates,
        labels,
        execution_frames,
        validation_start,
        validation_end,
        funding=funding,
    )
    write_decision(args.output / "UNIFIED_NARRATIVE", decision)

    delivery_diagnostics: dict[str, Any] = {}
    for name, family in (
        ("REVERSAL_DELIVERY_DIAGNOSTIC", EventFamily.LIQUIDITY_SWEEP_REVERSAL),
        ("CONTINUATION_DELIVERY_DIAGNOSTIC", EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION),
    ):
        scoped_candidates = [candidate for candidate in candidates if candidate.family == family]
        delivery_diagnostics[name] = {
            "selection_authority": False,
            "candidate_summary": _candidate_summary(scoped_candidates),
            "label_economics": _label_economics(_scope_rows(labels, family)),
        }

    aggregate_diagnostics = _aggregate_diagnostics(diagnostics_by_symbol)
    audit = _implementation_audit(aggregate_diagnostics, len(candidates), len(labels), decision)
    positive = decision.status == "POSITIVE_BASIC_ALPHA_OPEN_RISK_SEARCH"
    selected_configuration = decision.selected.configuration.identifier if decision.selected is not None else None
    selected_report = decision.selected.as_dict() if decision.selected is not None else None
    feature_rows = {
        symbol: {
            "rows": int(len(frame)),
            "columns": int(len(frame.columns)),
            "first_available_at": frame.index.min().isoformat() if not frame.empty else None,
            "last_available_at": frame.index.max().isoformat() if not frame.empty else None,
        }
        for symbol, frame in sorted(features.items())
    }

    summary = {
        "schema_version": 2,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "stage": "PRE2024_UNIFIED_SMC_COARSE_1M_NOT_RANKABLE",
        "evaluation_start": validation_start.isoformat(),
        "evaluation_end_exclusive": validation_end.isoformat(),
        "symbols": list(PRIMARY),
        "canonical_segments": list(args.segments),
        "corpus_digest_sha256": corpus_binding["manifest"]["corpus_digest_sha256"],
        "corpus_manifest_sha256": corpus_binding["manifest_sha256"],
        "rule_ontology_sha256": corpus_binding["ontology_sha256"],
        "instrument_rules_sha256": sha256_file(args.instrument_rules),
        "feature_frames": feature_rows,
        "candidate_summary": _candidate_summary(candidates),
        "narrative_diagnostics_by_symbol": diagnostics_by_symbol,
        "narrative_diagnostics_total": aggregate_diagnostics,
        "resolved_label_count": int(len(labels)),
        "event_labels_sha256": sha256_file(label_path),
        "unified_narrative": {
            "candidate_summary": _candidate_summary(candidates),
            "label_economics": _label_economics(labels),
            "decision": decision.as_dict(),
        },
        "delivery_mode_diagnostics": delivery_diagnostics,
        "implementation_audit": audit,
        "best_scope": "UNIFIED_NARRATIVE",
        "best_configuration": selected_configuration,
        "selected_configuration": selected_configuration,
        "best_report": selected_report,
        "best_scope_growth": None if decision.selected is None else float(decision.selected.metrics.geometric_daily_growth),
        "best_scope_status": decision.status,
        "promote_2024h1": bool(positive),
        "implementation_audit_required": not positive,
        "official_open_authority": False,
        "decision": (
            "ADVANCE_UNIFIED_SMC_NARRATIVE_TO_EVENT_TAPE"
            if positive
            else "KEEP_UNIFIED_SMC_NARRATIVE_AND_REPAIR_IMPLEMENTATION"
        ),
        "next_gate": (
            "event-tape replay of the exact unified-narrative survivor before any official 2024 opening"
            if positive
            else "repair the earliest blocked narrative stage, rerun the same causal SMC/ICT system, and reassess economics before changing the premise"
        ),
        "ranking_effect": "NONE_COARSE_SCREEN_NOT_RANKABLE",
    }
    summary_path = args.output / "PRIMARY_SCREEN_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "PRIMARY_SCREEN_SUMMARY.sha256").write_text(
        f"{sha256(summary_path.read_bytes()).hexdigest()}  {summary_path.name}\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--instrument-rules", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segments", nargs="+", required=True)
    parser.add_argument("--validation-start", default="2023-01-01T00:00:00Z")
    parser.add_argument("--validation-end-exclusive", default="2024-01-01T00:00:00Z")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
