from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

import cross_venue_execution_v5c as v5c
import cross_venue_pilot as v1
import cross_venue_pilot_v5 as pilot

_ORIGINAL_METRICS = v1.metrics
_METRICS_PATCHED = False
_ACTIVE_DAYS: tuple[str, ...] = tuple(v1.PILOT_DAYS)


def metrics_all_preregistered_days(trades) -> dict:
    result = _ORIGINAL_METRICS(trades)
    if not trades:
        result["positive_day_fraction"] = 0.0
        result["median_trades_per_day"] = 0.0
        result["day_returns_bps"] = {day: 0.0 for day in _ACTIVE_DAYS}
        return result
    frame = pd.DataFrame([asdict(item) for item in trades])
    daily = frame.groupby("day").net_bps.sum().reindex(_ACTIVE_DAYS, fill_value=0.0)
    counts = frame.groupby("day").size().reindex(_ACTIVE_DAYS, fill_value=0)
    result["positive_day_fraction"] = float((daily > 0).mean())
    result["median_trades_per_day"] = float(counts.median())
    result["day_returns_bps"] = daily.to_dict()
    return result


def patch_metrics(days: tuple[str, ...]) -> None:
    global _METRICS_PATCHED, _ACTIVE_DAYS
    if not days:
        raise ValueError("V5C pilot requires at least one preregistered sample day")
    _ACTIVE_DAYS = tuple(days)
    if not _METRICS_PATCHED:
        v1.metrics = metrics_all_preregistered_days
        _METRICS_PATCHED = True


def run(output: Path, cache: Path, days: tuple[str, ...] = v1.PILOT_DAYS) -> dict:
    v5c.patch_v5()
    patch_metrics(tuple(days))
    result = pilot.run(output, cache, tuple(days))
    result["causal_engine_version"] = v5c.ENGINE_VERSION
    result["protective_stop_contract"] = (
        "adverse of trigger-bucket executable extremum and delayed executable quote"
    )
    result["pilot_day_denominator"] = "all preregistered pilot dates including zero-trade dates"
    result["grid_alignment_contract"] = "decision, latency and hold are integer multiples of 100ms"
    result["v1_v2_v3_v4_v4b_v5_v5b_outputs_admissible"] = False
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
        "fatal_edge_pass_count": result["fatal_edge_pass_count"],
        "development_opened": False,
        "selection_opened": False,
        "2026_opened": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
