#!/usr/bin/env python3
"""Run the corpus-bound causal ML research path on canonical Bybit shards.

The 1-minute replay is only a coarse economic screen. A positive survivor must be
replayed on the separate event-tape lane before entering the official ranking.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from system.canonical_adapter import CanonicalInputConfig, assemble_symbol_frame
from system.coarse import CoarseExecutionConfig
from system.core import FeatureConfig, RiskConfig
from system.model import ModelConfig
from system.research_pipeline import (
    InstrumentRule,
    Pre2024Decision,
    ResearchConfiguration,
    configuration_sha256,
    generate_candidates_by_symbol,
    label_event_dataset,
    select_pre2024,
    write_decision,
)


PRIMARY = ("BTCUSDT", "ETHUSDT")
CONDITIONAL = ("SOLUSDT", "XRPUSDT")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def verify_corpus(corpus: Path) -> dict[str, Any]:
    manifest_path = corpus / "manifest.json"
    ontology_path = corpus / "rule_ontology_candidates.json"
    if not manifest_path.exists() or not ontology_path.exists():
        raise RuntimeError("complete corpus manifest and rule ontology are required")
    manifest = load_json(manifest_path)
    if manifest.get("decision") != "PASS_COMPLETE":
        raise RuntimeError(f"corpus is not complete: {manifest.get('decision')}")
    ontology = load_json(ontology_path)
    if ontology.get("corpus_digest_sha256") != manifest.get("corpus_digest_sha256"):
        raise RuntimeError("ontology/corpus digest mismatch")
    return {
        "manifest": manifest,
        "manifest_sha256": sha256_file(manifest_path),
        "ontology_sha256": sha256_file(ontology_path),
    }


def load_instrument_rules(path: Path, symbols: Sequence[str]) -> tuple[InstrumentRule, ...]:
    payload = load_json(path)
    rules: list[InstrumentRule] = []
    for symbol in symbols:
        row = payload.get(symbol)
        if not isinstance(row, dict):
            raise RuntimeError(f"instrument rule missing: {symbol}")
        step = float(row["quantity_step"])
        minimum = float(row["minimum_quantity"])
        if step <= 0 or minimum < 0:
            raise RuntimeError(f"invalid instrument rule: {symbol}")
        rules.append(InstrumentRule(symbol, step, minimum))
    return tuple(rules)


def load_canonical_frames(
    data_root: Path,
    repo_root: Path,
    symbols: Sequence[str],
    segments: Sequence[str],
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[tuple[str, pd.Timestamp], float]]:
    decision: dict[str, pd.DataFrame] = {}
    execution: dict[str, pd.DataFrame] = {}
    funding_map: dict[tuple[str, pd.Timestamp], float] = {}
    for symbol in symbols:
        decision[symbol], _ = assemble_symbol_frame(
            data_root,
            repo_root,
            symbol,
            segments,
            CanonicalInputConfig(trade_timeframe="5m", decision_timeframe_ms=300_000),
        )
        execution[symbol], funding = assemble_symbol_frame(
            data_root,
            repo_root,
            symbol,
            segments,
            CanonicalInputConfig(trade_timeframe="1m", decision_timeframe_ms=60_000),
        )
        for timestamp, row in funding.iterrows():
            if pd.notna(row.get("funding_rate")):
                funding_map[(symbol, pd.Timestamp(timestamp))] = float(row["funding_rate"])
    return decision, execution, funding_map


def basic_configurations(rules: tuple[InstrumentRule, ...]) -> list[ResearchConfiguration]:
    model_variants = {
        "SHALLOW": ModelConfig(max_leaf_nodes=7, min_samples_leaf=60, max_iter=220, l2_regularization=2.0),
        "MEDIUM": ModelConfig(max_leaf_nodes=15, min_samples_leaf=35, max_iter=300, l2_regularization=1.0),
        "LOCAL": ModelConfig(max_leaf_nodes=31, min_samples_leaf=20, max_iter=350, l2_regularization=2.5),
    }
    configurations: list[ResearchConfiguration] = []
    for model_name, model in model_variants.items():
        for cadence in (1, 7, 28):
            configurations.append(
                ResearchConfiguration(
                    identifier=f"BASIC_{model_name}_{cadence}D",
                    symbols=PRIMARY,
                    model=model,
                    update_cadence_days=cadence,
                    training_completion_lag_minutes=15,
                    passive_fill_threshold=0.55,
                    risk=RiskConfig(0.01, 5.0, 0.001),
                    instrument_rules=rules,
                )
            )
    return configurations


def _selected_config(decision: Pre2024Decision) -> ResearchConfiguration:
    if decision.selected is None:
        raise RuntimeError("no selected configuration")
    return decision.selected.configuration


def conditional_symbol_configurations(selected: ResearchConfiguration) -> list[ResearchConfiguration]:
    sets = (PRIMARY, (*PRIMARY, "SOLUSDT"), (*PRIMARY, "XRPUSDT"), (*PRIMARY, *CONDITIONAL))
    return [replace(selected, identifier=f"SYMBOLS_{'_'.join(symbols)}", symbols=tuple(symbols)) for symbols in sets]


def risk_configurations(selected: ResearchConfiguration) -> list[ResearchConfiguration]:
    configurations: list[ResearchConfiguration] = []
    for risk_fraction in (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.20):
        for leverage in (2.0, 5.0, 10.0, 20.0, 50.0, 100.0):
            configurations.append(
                replace(
                    selected,
                    identifier=f"RISK_{risk_fraction:.4f}_LEV_{leverage:.0f}",
                    risk=replace(selected.risk, risk_fraction=risk_fraction, maximum_leverage=leverage),
                )
            )
    return configurations


def run_pre2024(args: argparse.Namespace) -> int:
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    corpus_binding = verify_corpus(args.corpus)
    symbols = (*PRIMARY, *CONDITIONAL)
    rules = load_instrument_rules(args.instrument_rules, symbols)
    decision_frames, execution_frames, funding = load_canonical_frames(
        args.data_root,
        args.repo_root,
        symbols,
        args.segments,
    )
    _, candidates = generate_candidates_by_symbol(decision_frames, FeatureConfig())
    label_rows = label_event_dataset(candidates, execution_frames, CoarseExecutionConfig())
    label_path = output / "EVENT_LABELS.parquet"
    label_rows.to_parquet(label_path, index=False)

    validation_start = pd.Timestamp(args.validation_start)
    validation_end = pd.Timestamp(args.validation_end_exclusive)
    basic = select_pre2024(
        basic_configurations(rules),
        candidates,
        label_rows,
        execution_frames,
        validation_start,
        validation_end,
        funding=funding,
    )
    write_decision(output / "10_BASIC_ALPHA", basic)
    final = basic

    if basic.status == "POSITIVE_BASIC_ALPHA_OPEN_RISK_SEARCH":
        symbol_decision = select_pre2024(
            conditional_symbol_configurations(_selected_config(basic)),
            candidates,
            label_rows,
            execution_frames,
            validation_start,
            validation_end,
            funding=funding,
        )
        write_decision(output / "20_SYMBOL_SELECTION", symbol_decision)
        if symbol_decision.status == "POSITIVE_BASIC_ALPHA_OPEN_RISK_SEARCH":
            risk_decision = select_pre2024(
                risk_configurations(_selected_config(symbol_decision)),
                candidates,
                label_rows,
                execution_frames,
                validation_start,
                validation_end,
                funding=funding,
            )
            write_decision(output / "30_RISK_SELECTION", risk_decision)
            final = risk_decision
        else:
            final = symbol_decision

    summary = {
        "schema_version": 1,
        "stage": "PRE2024_COARSE_1M_NOT_RANKABLE",
        "corpus_digest_sha256": corpus_binding["manifest"]["corpus_digest_sha256"],
        "corpus_manifest_sha256": corpus_binding["manifest_sha256"],
        "rule_ontology_sha256": corpus_binding["ontology_sha256"],
        "canonical_segments": list(args.segments),
        "candidate_count": len(candidates),
        "resolved_training_row_count": len(label_rows),
        "event_labels_sha256": sha256_file(label_path),
        "final_decision": final.as_dict(),
        "official_open_authority": False,
        "next_gate": "event-tape replay of the exact frozen survivor" if final.status == "POSITIVE_BASIC_ALPHA_OPEN_RISK_SEARCH" else "close exact route and select a materially different corpus-supported payoff",
    }
    if final.selected is not None:
        summary["selected_configuration_sha256"] = configuration_sha256(final.selected.configuration)
    summary_path = output / "RUN_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "RUN_SUMMARY.sha256").write_text(f"{sha256_file(summary_path)}  {summary_path.name}\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("pre2024",), default="pre2024")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--instrument-rules", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--segments", nargs="+", required=True)
    parser.add_argument("--validation-start", default="2023-01-01T00:00:00Z")
    parser.add_argument("--validation-end-exclusive", default="2024-01-01T00:00:00Z")
    args = parser.parse_args(argv)
    return run_pre2024(args)


if __name__ == "__main__":
    raise SystemExit(main())
