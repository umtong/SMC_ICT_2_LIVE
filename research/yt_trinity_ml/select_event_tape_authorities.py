#!/usr/bin/env python3
"""Select every coarse result whose target path requires event-tape validation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


TARGET_DECISIONS = {
    "TARGET_EXCEEDED_COARSE_EVENT_TAPE_REQUIRED",
    "TARGET_POSSIBLE_ONLY_WITH_EXECUTION_EDGE_EVENT_TAPE_REQUIRED",
}


def add_single(path: Path, rows: list[dict[str, Any]]) -> None:
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    decision = str(payload.get("decision") or "")
    if decision not in TARGET_DECISIONS:
        return
    metrics = payload.get("realistic_metrics")
    zero = payload.get("zero_friction_metrics_same_signals")
    if not isinstance(metrics, Mapping) or not isinstance(zero, Mapping):
        return
    rows.append({
        "authority_key": "single_full_survivor",
        "source_pointer": path.name,
        "source_pointer_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "run_id": int(payload["run_id"]),
        "source_sha": payload.get("source_sha"),
        "artifact_name": payload.get("artifact_name"),
        "decision": decision,
        "strategy_id": payload.get("strategy_id"),
        "route_key": payload.get("route_key"),
        "realistic_metrics": metrics,
        "zero_friction_metrics": zero,
        "evidence": payload.get("evidence"),
    })


def add_pooled(path: Path, rows: list[dict[str, Any]]) -> None:
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    decision = str(payload.get("decision") or "")
    if decision not in TARGET_DECISIONS:
        return
    official = payload.get("official_full_period")
    if not isinstance(official, Mapping):
        return
    metrics = official.get("realistic_metrics")
    zero = official.get("zero_friction_metrics_same_signals")
    if not isinstance(metrics, Mapping) or not isinstance(zero, Mapping):
        return
    rows.append({
        "authority_key": "pooled_trinity",
        "source_pointer": path.name,
        "source_pointer_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "run_id": int(payload["run_id"]),
        "source_sha": payload.get("source_sha"),
        "artifact_name": payload.get("artifact_name"),
        "decision": decision,
        "strategy_id": payload.get("strategy_id"),
        "route_key": "pooled_trinity",
        "realistic_metrics": metrics,
        "zero_friction_metrics": zero,
        "evidence": official.get("evidence"),
    })


def key(row: Mapping[str, Any]):
    metrics = row["realistic_metrics"]
    return (
        float(metrics.get("geometric_daily_growth") or 0.0),
        float(metrics.get("account_multiple") or 0.0),
        -float(metrics.get("maximum_drawdown") or 1.0),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
    add_single(args.root / "FULL_SEQUENTIAL_COARSE_POINTER.json", rows)
    add_pooled(args.root / "POOLED_TRINITY_RUN_POINTER.json", rows)
    rows.sort(key=key, reverse=True)
    decision = "EVENT_TAPE_AUTHORITIES_READY" if rows else "NO_EVENT_TAPE_AUTHORITY"
    payload = {
        "schema_version": 1,
        "decision": decision,
        "authority_count": len(rows),
        "authorities": rows,
        "rankable": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
