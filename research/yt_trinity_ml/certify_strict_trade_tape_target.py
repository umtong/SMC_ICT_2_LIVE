#!/usr/bin/env python3
"""Certify a target-path result only after corpus binding and strict trade-tape stress."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


TARGET_BASELINE = {
    "TARGET_EXCEEDED_PUBLIC_TRADE_TAPE_PENDING_STRICT_STRESS",
    "TARGET_EXCEEDED_PUBLIC_TRADE_TAPE_PENDING_QUOTE_STRESS",
}
TARGET_STRICT = {"TARGET_EXCEEDED_STRICT_PUBLIC_TRADE_TAPE"}
EXPECTED_CALENDAR_DAYS = 912


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_metrics(metrics: Any) -> bool:
    return (
        isinstance(metrics, Mapping)
        and int(metrics.get("calendar_days") or 0) == EXPECTED_CALENDAR_DAYS
        and float(metrics.get("geometric_daily_growth") or -1.0) >= 0.01
        and float(metrics.get("account_multiple") or 0.0) > 1.0
        and not bool(metrics.get("liquidated_or_invalid"))
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract_path = args.root / "CORPUS_BOUND_SYSTEM_CONTRACT.json"
    corpus_run_path = args.root / "CORPUS_BOUND_RUN_POINTER.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8")) if contract_path.exists() else None
    corpus_run = json.loads(corpus_run_path.read_text(encoding="utf-8")) if corpus_run_path.exists() else None
    corpus_ready = (
        isinstance(contract, Mapping)
        and contract.get("status") == "FROZEN"
        and contract.get("decision") == "CORPUS_BOUND_PRE2024_SELECTION_READY"
        and contract.get("corpus_binding", {}).get("manifest_decision") in {
            "PASS_COMPLETE",
            "PASS_NATIVE_CAPTION_CLASSIFICATION",
        }
        and isinstance(corpus_run, Mapping)
        and corpus_run.get("strategy_id") == contract.get("system_id")
        and corpus_run.get("frozen_config_sha256")
        and corpus_run.get("corpus_binding")
    )
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for strict_path in sorted(args.root.glob("STRICT_TRADE_TAPE_RESULT_*.json")):
        strict = json.loads(strict_path.read_text(encoding="utf-8"))
        baseline_name = str(strict.get("baseline_pointer") or "")
        baseline_path = args.root / baseline_name
        if not baseline_path.exists():
            rejected.append({"strict_pointer": strict_path.name, "reason": "baseline_pointer_missing"})
            continue
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        route_key = str(strict.get("route_key") or baseline.get("route_key") or "")
        strategy_id = str(strict.get("strategy_id") or baseline.get("strategy_id") or "")
        strict_metrics = strict.get("metrics")
        baseline_metrics = baseline.get("metrics")
        checks = {
            "baseline_target_decision": baseline.get("decision") in TARGET_BASELINE,
            "strict_target_decision": strict.get("decision") in TARGET_STRICT,
            "baseline_metrics_valid": valid_metrics(baseline_metrics),
            "strict_metrics_valid": valid_metrics(strict_metrics),
            "same_source_authority": (
                int(strict.get("source_authority_run_id") or -1)
                == int(baseline.get("source_authority_run_id") or -2)
                and strict.get("source_authority_artifact")
                == baseline.get("source_authority_artifact")
            ),
            "strict_same_frozen_size": bool(strict.get("sizing_config")),
            "corpus_bound_route": route_key == "corpus_bound_pool",
            "corpus_contract_ready": corpus_ready,
            "strategy_matches_corpus_contract": (
                isinstance(contract, Mapping)
                and strategy_id == contract.get("system_id")
            ),
        }
        passed = all(checks.values())
        row = {
            "strict_pointer": strict_path.name,
            "strict_pointer_sha256": sha(strict_path),
            "baseline_pointer": baseline_path.name,
            "baseline_pointer_sha256": sha(baseline_path),
            "route_key": route_key,
            "strategy_id": strategy_id,
            "checks": checks,
            "baseline": baseline,
            "strict": strict,
            "certifiable": passed,
        }
        if passed:
            candidates.append(row)
        else:
            rejected.append(row)
    candidates.sort(
        key=lambda row: (
            float(row["strict"]["metrics"]["geometric_daily_growth"]),
            float(row["strict"]["metrics"]["account_multiple"]),
            -float(row["strict"]["metrics"].get("maximum_drawdown") or 1.0),
        ),
        reverse=True,
    )
    selected = candidates[0] if candidates else None
    if selected:
        identity = {
            "strategy_id": selected["strategy_id"],
            "contract_sha256": sha(contract_path),
            "corpus_run_pointer_sha256": sha(corpus_run_path),
            "baseline_pointer_sha256": selected["baseline_pointer_sha256"],
            "strict_pointer_sha256": selected["strict_pointer_sha256"],
        }
        result_id = "YTTRINITY-STRICT-" + hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16].upper()
        decision = "TARGET_CERTIFIED_CORPUS_BOUND_STRICT_PUBLIC_TRADE_TAPE"
        rankable = True
        result = {
            "result_id": result_id,
            "strategy_id": selected["strategy_id"],
            "verification_stage": "CORPUS_BOUND_FULL_PERIOD_PUBLIC_TRADE_TAPE_STRICT_STRESS",
            "baseline_metrics": selected["baseline"]["metrics"],
            "strict_metrics": selected["strict"]["metrics"],
            "baseline_pointer": selected["baseline_pointer"],
            "strict_pointer": selected["strict_pointer"],
            "frozen_config_sha256": corpus_run.get("frozen_config_sha256"),
            "corpus_binding": corpus_run.get("corpus_binding"),
            "contract_sha256": sha(contract_path),
            "comparison_confidence": "MEDIUM_HIGH_STRICT_TRADE_TAPE_NO_DIRECT_HISTORICAL_DISPLAYED_DEPTH",
            "known_vulnerabilities": [
                "historical displayed order-book depth is not directly observed",
                "trade-tape queue and impact are conservative modeled envelopes rather than reconstructed exchange queue IDs",
                "live latency measurement and real-time paper operation remain deployment approval tasks",
            ],
        }
    else:
        decision = "NO_CERTIFIABLE_STRICT_CORPUS_BOUND_TARGET"
        rankable = False
        result = None
    payload = {
        "schema_version": 1,
        "decision": decision,
        "rankable": rankable,
        "result": result,
        "certifiable_candidate_count": len(candidates),
        "rejected": rejected,
        "expected_calendar_days": EXPECTED_CALENDAR_DAYS,
        "target_geometric_daily_growth": 0.01,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.write_text(raw, encoding="utf-8")
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(
        f"{hashlib.sha256(raw.encode('utf-8')).hexdigest()}  {args.output.name}\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
