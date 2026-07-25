from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cross_venue_development_v5 as development
import cross_venue_execution_v5b as v5b


def validate_pilot_v5b(pilot_dir: Path) -> dict:
    path = pilot_dir / "PILOT_RESULT.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("causal_version") != v5b.CAUSAL_VERSION:
        raise ValueError("pilot causal version is not V5")
    if result.get("causal_engine_version") != "5B":
        raise ValueError("pilot did not use the funding-safe V5B engine")
    if result.get("v1_v2_v3_v4_v4b_v5_outputs_admissible") is not False:
        raise ValueError("pilot did not explicitly block all earlier engines")
    if not result.get("funding_boundary_contract"):
        raise ValueError("pilot is missing the frozen funding-boundary contract")
    return result


def run(pilot_dir: Path, output: Path, cache: Path) -> dict:
    validate_pilot_v5b(pilot_dir)
    v5b.patch_v5()
    result = development.run(pilot_dir, output, cache)
    result["causal_engine_version"] = "5B"
    result["funding_boundary_contract"] = (
        "exclude any entry whose maximum hold plus exit latency and bounded bucket rounding can cross an 8h settlement"
    )
    result["v1_v2_v3_v4_v4b_v5_promotion_admissible"] = False
    path = output / "DEVELOPMENT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (output / "DEVELOPMENT_RESULT.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.pilot_dir, args.output, args.cache)
    print(json.dumps({
        "stage": result["stage"],
        "causal_engine_version": result["causal_engine_version"],
        "development_gate_pass_count": int(result.get("development_gate_pass_count", 0)),
        "selection_opened": False,
        "2026_opened": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
