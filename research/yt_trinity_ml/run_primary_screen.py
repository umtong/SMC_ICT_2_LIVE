#!/usr/bin/env python3
"""Run the first causal 2023 BTC/ETH economic screen for the complete corpus alpha.

This lane deliberately excludes SOL/XRP and risk/leverage search. It asks the only
high-information first question: does the frozen BTC/ETH structural alpha have positive
after-cost geometric growth at the basic risk setting? Reversal, continuation, and
combined routes are reported separately so an economic failure closes the responsible
payoff mechanism instead of inviting threshold micro-tuning.
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
from system.research_pipeline import (
    Pre2024Decision,
    generate_candidates_by_symbol,
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
    result["passive_net_r_given_fill"] = _finite_stats(filled["passive_net_r"]) if not filled.empty else _finite_stats(pd.Series(dtype=float))
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
        "by_family": dict(sorted(Counter(candidate.family.value for candidate in candidates).items())),
        "by_side": dict(sorted(Counter(str(candidate.side) for candidate in candidates).items())),
        "raw_structural_reward_risk": _finite_stats(rr),
        "first_timestamp": min(candidate.timestamp for candidate in candidates).isoformat(),
        "last_timestamp": max(candidate.timestamp for candidate in candidates).isoformat(),
    }


def _decision_growth(decision: Pre2024Decision) -> float:
    if decision.selected is None:
        return float("-inf")
    return float(decision.selected.metrics.geometric_daily_growth)


def _scope_rows(labels: pd.DataFrame, family: EventFamily | None) -> pd.DataFrame:
    if family is None or labels.empty:
        return labels.copy()
    return labels[labels["family"].eq(family.value)].copy()


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
    features, candidates = generate_candidates_by_symbol(decision_frames, FeatureConfig())
    labels = label_event_dataset(candidates, execution_frames, CoarseExecutionConfig())
    label_path = args.output / "EVENT_LABELS.parquet"
    labels.to_parquet(label_path, index=False)

    validation_start = pd.Timestamp(args.validation_start)
    validation_end = pd.Timestamp(args.validation_end_exclusive)
    scopes: tuple[tuple[str, EventFamily | None], ...] = (
        ("COMBINED", None),
        ("REVERSAL", EventFamily.LIQUIDITY_SWEEP_REVERSAL),
        ("CONTINUATION", EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION),
    )
    scope_payload: dict[str, Any] = {}
    decisions: dict[str, Pre2024Decision] = {}
    for scope, family in scopes:
        scoped_candidates = [candidate for candidate in candidates if family is None or candidate.family == family]
        scoped_labels = _scope_rows(labels, family)
        decision = select_pre2024(
            basic_configurations(rules),
            scoped_candidates,
            scoped_labels,
            execution_frames,
            validation_start,
            validation_end,
            funding=funding,
        )
        write_decision(args.output / scope, decision)
        decisions[scope] = decision
        scope_payload[scope] = {
            "candidate_summary": _candidate_summary(scoped_candidates),
            "label_economics": _label_economics(scoped_labels),
            "decision": decision.as_dict(),
        }

    best_scope = max(decisions, key=lambda name: (_decision_growth(decisions[name]), name))
    best_decision = decisions[best_scope]
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
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "stage": "PRE2024_PRIMARY_COARSE_1M_NOT_RANKABLE",
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
        "resolved_label_count": int(len(labels)),
        "event_labels_sha256": sha256_file(label_path),
        "scopes": scope_payload,
        "best_scope": best_scope,
        "best_scope_growth": None if best_decision.selected is None else float(best_decision.selected.metrics.geometric_daily_growth),
        "best_scope_status": best_decision.status,
        "official_open_authority": False,
        "decision": (
            "ADVANCE_EXACT_SURVIVOR_TO_EVENT_TAPE"
            if best_decision.status == "POSITIVE_BASIC_ALPHA_OPEN_RISK_SEARCH"
            else "ECONOMIC_FAIL_SWITCH_PAYOFF_MECHANISM"
        ),
        "next_gate": (
            "event-tape replay of the exact frozen basic-risk survivor before any 2024 opening"
            if best_decision.status == "POSITIVE_BASIC_ALPHA_OPEN_RISK_SEARCH"
            else "inspect family-level economics and replace the structurally failing payoff mechanism; do not tune risk or leverage"
        ),
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
