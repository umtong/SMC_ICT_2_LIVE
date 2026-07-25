from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cross_venue_execution_v5b as v5b
import cross_venue_pilot_v5 as pilot


def run(output: Path, cache: Path) -> dict:
    v5b.patch_v5()
    result = pilot.run(output, cache)
    result["causal_engine_version"] = "5B"
    result["funding_boundary_contract"] = (
        "exclude any entry whose maximum hold plus exit latency and bounded bucket rounding can cross an 8h settlement"
    )
    result["v1_v2_v3_v4_v4b_v5_outputs_admissible"] = False
    path = output / "PILOT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (output / "PILOT_RESULT.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output, args.cache)
    print(json.dumps({
        "stage": result["stage"],
        "causal_engine_version": result["causal_engine_version"],
        "fatal_edge_pass_count": result["fatal_edge_pass_count"],
        "development_opened": False,
        "2026_opened": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
