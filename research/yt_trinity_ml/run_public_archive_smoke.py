#!/usr/bin/env python3
"""Run the tentative causal engine on official Bybit public kline archives.

This lane is deliberately NOT corpus-bound, omits historical funding, uses trade-close
as a coarse mark proxy, and therefore cannot open an official period or enter ranking.
Its only authority is to expose engineering/economic failures before the transcript
ontology is frozen.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Any, Sequence

import pandas as pd

from system.coarse import CoarseExecutionConfig
from system.core import FeatureConfig, RiskConfig
from system.model import ModelConfig
from system.public_archive import build_frames, utc_timestamp, write_manifest
from system.research_pipeline import (
    InstrumentRule,
    ResearchConfiguration,
    configuration_sha256,
    evaluate_configuration,
    generate_candidates_by_symbol,
    label_event_dataset,
)


DEFAULT_RULES = {
    "BTCUSDT": InstrumentRule("BTCUSDT", 0.001, 0.001),
    "ETHUSDT": InstrumentRule("ETHUSDT", 0.01, 0.01),
    "SOLUSDT": InstrumentRule("SOLUSDT", 0.1, 0.1),
    "XRPUSDT": InstrumentRule("XRPUSDT", 1.0, 1.0),
}


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--data-start", default="2022-07-01T00:00:00Z")
    parser.add_argument("--evaluation-start", default="2023-01-01T00:00:00Z")
    parser.add_argument("--evaluation-end-exclusive", default="2023-07-01T00:00:00Z")
    parser.add_argument("--update-cadence-days", type=int, default=28)
    parser.add_argument("--training-completion-lag-minutes", type=int, default=15)
    args = parser.parse_args(argv)

    symbols = tuple(str(symbol).upper() for symbol in args.symbols)
    unknown = sorted(set(symbols) - set(DEFAULT_RULES))
    if unknown:
        raise SystemExit(f"unsupported symbols: {unknown}")
    if len(set(symbols)) != len(symbols):
        raise SystemExit("symbols must be unique")

    data_start = utc_timestamp(args.data_start)
    evaluation_start = utc_timestamp(args.evaluation_start)
    evaluation_end = utc_timestamp(args.evaluation_end_exclusive)
    if not data_start < evaluation_start < evaluation_end:
        raise SystemExit("require data_start < evaluation_start < evaluation_end_exclusive")

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}

    started = monotonic()
    decision_frames, execution_frames, archive_manifest = build_frames(
        args.cache_root,
        symbols,
        data_start,
        evaluation_end,
        execution_interval_minutes=1,
        decision_interval_minutes=5,
    )
    timings["archive_load_seconds"] = round(monotonic() - started, 3)
    write_manifest(output / "PUBLIC_ARCHIVE_MANIFEST.json", archive_manifest)

    started = monotonic()
    features, candidates = generate_candidates_by_symbol(decision_frames, FeatureConfig())
    timings["feature_and_candidate_seconds"] = round(monotonic() - started, 3)
    feature_rows = {symbol: len(frame) for symbol, frame in features.items()}
    del features

    started = monotonic()
    execution_config = CoarseExecutionConfig()
    labels = label_event_dataset(candidates, execution_frames, execution_config)
    timings["label_seconds"] = round(monotonic() - started, 3)
    labels_path = output / "EVENT_LABELS.parquet"
    labels.to_parquet(labels_path, index=False)

    rules = tuple(DEFAULT_RULES[symbol] for symbol in symbols)
    configuration = ResearchConfiguration(
        identifier=f"ENGINEERING_SMOKE_{'_'.join(symbols)}_{args.update_cadence_days}D",
        symbols=symbols,
        model=ModelConfig(
            learning_rate=0.05,
            max_leaf_nodes=15,
            max_iter=250,
            min_samples_leaf=35,
            l2_regularization=1.0,
            calibration_fraction=0.20,
            lower_confidence_penalty=0.35,
        ),
        update_cadence_days=args.update_cadence_days,
        training_completion_lag_minutes=args.training_completion_lag_minutes,
        passive_fill_threshold=0.55,
        risk=RiskConfig(0.01, 5.0, 0.001),
        instrument_rules=rules,
    )

    started = monotonic()
    result = evaluate_configuration(
        configuration,
        candidates,
        labels,
        execution_frames,
        evaluation_start,
        evaluation_end,
        initial_nav=10000.0,
        execution_config=execution_config,
        funding=None,
    )
    timings["walk_forward_and_replay_seconds"] = round(monotonic() - started, 3)

    family_counts: dict[str, int] = {}
    symbol_counts: dict[str, int] = {}
    for candidate in candidates:
        family_counts[candidate.family.value] = family_counts.get(candidate.family.value, 0) + 1
        symbol_counts[candidate.symbol] = symbol_counts.get(candidate.symbol, 0) + 1

    summary = {
        "schema_version": 1,
        "stage": "ENGINEERING_SMOKE_NOT_CORPUS_BOUND_NOT_RANKABLE",
        "official_open_authority": False,
        "ranking_authority": False,
        "data_start": data_start.isoformat(),
        "evaluation_start": evaluation_start.isoformat(),
        "evaluation_end_exclusive": evaluation_end.isoformat(),
        "symbols": list(symbols),
        "feature_rows": feature_rows,
        "candidate_count": len(candidates),
        "candidate_counts_by_symbol": symbol_counts,
        "candidate_counts_by_family": family_counts,
        "resolved_label_count": len(labels),
        "label_event_end_max": (pd.Timestamp(labels["event_end"].max()).isoformat() if not labels.empty else None),
        "configuration": jsonable(asdict(configuration)),
        "configuration_sha256": configuration_sha256(configuration),
        "execution_config": asdict(execution_config),
        "result": result.as_dict(),
        "timings": timings,
        "public_archive_manifest_sha256": file_sha256(output / "PUBLIC_ARCHIVE_MANIFEST.json"),
        "event_labels_sha256": file_sha256(labels_path),
        "known_limitations": [
            "transcript corpus and rule ontology are not yet frozen or bound",
            "historical funding is omitted",
            "trade close is used as coarse mark proxy",
            "spread is a configured floor rather than observed bid/ask",
            "one-minute OHLC stop-first replay is not event-tape execution",
            "passive partial fills and queue position are not observable",
            "instrument quantity rules are engineering defaults, not time-versioned exchange snapshots",
        ],
        "next_gate": "bind a PASS_COMPLETE transcript ontology, rerun exact frozen system, then event-tape replay any positive survivor",
    }
    summary_path = output / "RUN_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{file_sha256(path)}  {path.name}\n"
            for path in sorted(output.iterdir())
            if path.is_file() and path.name != "SHA256SUMS"
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
