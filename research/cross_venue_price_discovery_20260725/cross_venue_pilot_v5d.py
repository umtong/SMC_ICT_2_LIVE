from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cross_venue_execution_v5d as v5d
import cross_venue_failclosed_v5d as failclosed_v5d
import cross_venue_performance_v5d as performance_v5d
import cross_venue_pilot as v1
import cross_venue_pilot_cache_v5d as pilot_cache_v5d
import cross_venue_pilot_fast_exit_v5d as fast_exit_v5d
import cross_venue_pilot_v5c as pilot_v5c


def run(output: Path, cache: Path, days: tuple[str, ...] = v1.PILOT_DAYS) -> dict:
    # These patches alter only repeated computation, never the scientific path:
    # 1. build the immutable executable-quote index once per aligned frame;
    # 2. omit fixed-pilot drawdown marks that are not consumed by any pilot metric,
    #    while preserving exact stop/convergence/horizon and fail-closed exits;
    # 3. replay each semantically unique signal/execution path once and copy
    #    the resulting immutable trades to duplicate Cartesian-grid config IDs.
    performance_v5d.patch()
    failclosed_v5d.patch()
    fast_exit_v5d.patch()
    pilot_cache_v5d.clear()
    pilot_cache_v5d.patch()
    result = pilot_v5c.run(output, cache, tuple(days))
    result["stage"] = "MICROSECOND_LOCAL_ARRIVAL_FATAL_EDGE_PILOT_V5D"
    result["causal_engine_version"] = v5d.ENGINE_VERSION
    result["funding_boundary_contract"] = (
        "exclude any entry whose maximum hold, exit latency and bounded bucket rounding can cross an 8h settlement"
    )
    result["source_continuity_contract"] = (
        "complete 100ms grid; rolling signal and convergence state reset after unavailable Binance/Bybit state"
    )
    result["execution_gap_contract"] = (
        "entry quote delays over 1s are not filled; post-entry unavailable state or delayed exits receive a punitive exit"
    )
    result["exit_floor_contract"] = "no economic 10%-of-quote floor; numerical positive floor only"
    result["drawdown_contract"] = "single chronological marked account path without closed-plus-intratrade double counting"
    result["performance_contract"] = (
        "immutable first-executable-quote and fixed-pilot exit arrays are cached per frame; "
        "unused fixed-pilot drawdown marks are omitted; 768 registered rows are reproduced "
        "from 288 semantically unique gross execution paths"
    )
    result["v1_v2_v3_v4_v4b_v5_v5b_v5c_outputs_admissible"] = False
    result["ranking_eligible"] = False
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
        "fatal_edge_pass_count": int(result.get("fatal_edge_pass_count", 0)),
        "development_opened": False,
        "selection_opened": False,
        "2026_opened": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
