from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cross_venue_development_v5 as development
import cross_venue_execution_v5b as v5b


def run(pilot_dir: Path, output: Path, cache: Path) -> dict:
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
