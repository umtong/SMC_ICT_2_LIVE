from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--latency100", required=True)
    p.add_argument("--latency300", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    r100_path = Path(args.latency100) / "RESULT.json"
    r300_path = Path(args.latency300) / "RESULT.json"
    r100 = json.loads(r100_path.read_text())
    r300 = json.loads(r300_path.read_text())
    both = bool(r100.get("all_gates_pass")) and bool(r300.get("all_gates_pass"))
    adequate = not any(
        r.get("hard_validity_status") == "PASS_PRE_MODEL_EVENT_OR_CLASS_SCARCITY"
        for r in (r100, r300)
    )
    combined = {
        "claim_id": "CLM-20260726-2036-ML-XVENUE-MAKER-001",
        "result_id": "RES-20260726-ML-XVENUE-MAKER-001",
        "status": "PRE2024_EXPANSION_SURVIVOR" if both else "TESTED_BELOW_GATE",
        "hard_validity_status": "PASS_INITIAL_CAUSAL_QUEUE_AWARE_SCREEN" if adequate else "PASS_PRE_MODEL_EVENT_OR_CLASS_SCARCITY",
        "economic_status": "SURVIVOR_REQUIRES_PRE2024_EXPANSION" if both else "BELOW_GATE",
        "ranking_role": "NONE_NOT_RANK_ELIGIBLE_PRE2024_FATAL_SCREEN",
        "latencies": {"100ms": r100, "300ms": r300},
        "both_latency_gates_pass": both,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
        "decision": "EXPAND_UNCHANGED_PRE2024_INFORMATION_UNIT" if both else "RETIRE_EXACT_XVENUE_MAKER_INFORMATION_UNIT",
        "input_result_sha256": {"100ms": sha256(r100_path), "300ms": sha256(r300_path)},
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(combined, indent=2, sort_keys=True, allow_nan=True) + "\n")
    print(json.dumps(combined, indent=2, sort_keys=True, allow_nan=True))


if __name__ == "__main__":
    main()
