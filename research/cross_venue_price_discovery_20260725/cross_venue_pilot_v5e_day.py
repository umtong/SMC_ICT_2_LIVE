from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cross_venue_pilot as v1
import cross_venue_pilot_v5d as v5d


def run(day: str, output: Path, cache: Path) -> dict:
    if day not in v1.PILOT_DAYS:
        raise ValueError(f"day is not in the frozen pilot set: {day}")
    result = v5d.run(output, cache, (day,))
    result["parallel_shard_day"] = day
    result["parallel_shard_contract"] = (
        "one frozen UTC sample day; configurations and gross paths are unchanged; "
        "cross-day global-slot overlap is impossible because sample dates are disjoint"
    )
    path = output / "PILOT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (output / "PILOT_RESULT.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.day, args.output, args.cache)
    print(json.dumps({
        "day": args.day,
        "causal_engine_version": result["causal_engine_version"],
        "configurations": result["configurations"],
        "fatal_edge_pass_count_on_shard": result["fatal_edge_pass_count"],
        "orders_submitted": result["orders_submitted"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
