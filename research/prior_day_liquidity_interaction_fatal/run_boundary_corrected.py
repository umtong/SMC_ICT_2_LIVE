from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run as base

CORRECTION_ID = "CORRECTION-20260730-PRIOR-DAY-STAGE-BOUNDARY-MARK-001"
PRE2024_BOUNDARY_MS = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)


def _last_observed_index_before(data: dict[str, np.ndarray], boundary_ms: int) -> int | None:
    index = int(np.searchsorted(data["t"], boundary_ms, side="left")) - 1
    while index >= 0 and not bool(data["observed"][index]):
        index -= 1
    return index if index >= 0 else None


def state_exit_ms_until(
    candidate: base.EventCandidate,
    data: dict[str, np.ndarray],
    boundary_ms: int,
) -> int | None:
    start = int(
        np.searchsorted(data["five_available"], candidate.decision_ms, side="right")
    )
    stop = int(np.searchsorted(data["five_available"], boundary_ms, side="left"))
    if stop <= start:
        return None
    closes = data["five_close"][start:stop]
    if candidate.action == "ACCEPT":
        condition = (
            closes < candidate.level
            if candidate.side_level == "upper"
            else closes > candidate.level
        )
    else:
        condition = (
            closes > candidate.level
            if candidate.side_level == "upper"
            else closes < candidate.level
        )
    hits = np.flatnonzero(condition)
    if len(hits) == 0:
        return None
    decision_available = int(data["five_available"][start + int(hits[0])])
    executable = decision_available + 60_000
    return executable if executable < boundary_ms else None


def simulate_until(
    candidate: base.EventCandidate,
    data: dict[str, np.ndarray],
    boundary_ms: int,
) -> dict[str, object] | None:
    if candidate.entry_ms >= boundary_ms:
        return None
    entry_index = int(np.searchsorted(data["t"], candidate.entry_ms, side="left"))
    if (
        entry_index >= len(data["t"])
        or int(data["t"][entry_index]) != candidate.entry_ms
        or not bool(data["observed"][entry_index])
    ):
        return None

    mark_index = _last_observed_index_before(data, boundary_ms)
    if mark_index is None or mark_index < entry_index:
        return None

    entry = float(data["open"][entry_index])
    stop = float(candidate.stop_price)
    if candidate.direction == 1:
        if not stop < entry:
            return None
        target = (
            float(candidate.target_price)
            if np.isfinite(candidate.target_price)
            else entry + base.RR * (entry - stop)
        )
        if not target > entry:
            return None
    else:
        if not stop > entry:
            return None
        target = (
            float(candidate.target_price)
            if np.isfinite(candidate.target_price)
            else entry - base.RR * (stop - entry)
        )
        if not target < entry:
            return None

    failure_ms = state_exit_ms_until(candidate, data, boundary_ms)
    failure_index = (
        int(np.searchsorted(data["t"], failure_ms, side="left"))
        if failure_ms is not None
        else None
    )
    search_end = mark_index + 1
    if failure_index is not None:
        search_end = min(search_end, failure_index)

    highs = data["high"][entry_index:search_end]
    lows = data["low"][entry_index:search_end]
    if candidate.direction == 1:
        stops = np.flatnonzero(lows <= stop)
        targets = np.flatnonzero(highs >= target)
    else:
        stops = np.flatnonzero(highs >= stop)
        targets = np.flatnonzero(lows <= target)
    stop_hit = int(stops[0]) if len(stops) else None
    target_hit = int(targets[0]) if len(targets) else None

    if stop_hit is not None and (target_hit is None or stop_hit <= target_hit):
        exit_index = entry_index + stop_hit
        opened = float(data["open"][exit_index])
        exit_price = min(stop, opened) if candidate.direction == 1 else max(stop, opened)
        reason = "STOP_FIRST_AMBIGUOUS" if stop_hit == target_hit else "STOP"
        completed = True
        exit_ms = int(data["t"][exit_index])
    elif target_hit is not None:
        exit_index = entry_index + target_hit
        exit_price = target
        reason = "TARGET"
        completed = True
        exit_ms = int(data["t"][exit_index])
    elif (
        failure_index is not None
        and failure_index <= mark_index
        and int(data["t"][failure_index]) < boundary_ms
        and bool(data["observed"][failure_index])
    ):
        exit_index = failure_index
        exit_price = float(data["open"][exit_index])
        reason = "STATE_FAILURE"
        completed = True
        exit_ms = int(data["t"][exit_index])
    else:
        exit_index = mark_index
        exit_price = float(data["close"][exit_index])
        reason = "MARK_STAGE_BOUNDARY"
        completed = False
        exit_ms = boundary_ms

    gross = candidate.direction * (exit_price / entry - 1.0)
    funding = base.funding_fraction(
        data, candidate.entry_ms, exit_ms, entry, candidate.direction
    )
    return {
        **asdict(candidate),
        "entry_price": entry,
        "stop_price_actual": stop,
        "target_price_actual": target,
        "exit_ms": exit_ms,
        "exit_price": exit_price,
        "exit_reason": reason,
        "completed": completed,
        "forced_boundary_close": False,
        "gross_fraction": float(gross),
        "funding_fraction": float(funding),
        "stop_fraction": abs(entry - stop) / entry,
        "holding_min": (exit_ms - candidate.entry_ms) / 60_000.0,
    }


def replay_with_marks(
    frame: pd.DataFrame, cost_bps: float
) -> tuple[dict[str, float | int], pd.DataFrame]:
    metrics, ledger = base.replay(frame, cost_bps)
    metrics["marked_count"] = (
        int(ledger["exit_reason"].eq("MARK_STAGE_BOUNDARY").sum())
        if not ledger.empty
        else 0
    )
    return metrics, ledger


def evaluate_source(
    source: pd.DataFrame,
    *,
    action: str,
    period: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    action_source = source[source["action"].eq(action)].copy()
    for cost in base.COSTS_BPS:
        selected = base.route(action_source)
        metrics, ledger = replay_with_marks(selected, cost)
        positive = ledger[ledger["pnl"] > 0].sort_values("pnl", ascending=False)
        removed_count = math.ceil(0.10 * len(positive)) if len(positive) else 0
        removed = set(positive.head(removed_count)["event_id"])
        rerouted = base.route(action_source[~action_source["event_id"].isin(removed)])
        winner_removed, _ = replay_with_marks(rerouted, cost)
        rows.append(
            {
                "action": action,
                "period": period,
                "cost": int(cost),
                "candidate_outcomes": len(action_source),
                **metrics,
                "winner_removed_multiple": winner_removed["multiple"],
                "winner_removed_trades": winner_removed["trades"],
                "removed_positive_events": removed_count,
            }
        )
    return rows


def _simulate_candidates(
    candidates: list[base.EventCandidate],
    data: dict[str, dict[str, np.ndarray]],
    boundary_ms: int,
    start_ms: int | None = None,
) -> pd.DataFrame:
    outcomes: list[dict[str, object]] = []
    for candidate in candidates:
        if start_ms is not None and candidate.entry_ms < start_ms:
            continue
        result = simulate_until(candidate, data[candidate.symbol], boundary_ms)
        if result is not None:
            outcomes.append(result)
    frame = pd.DataFrame(outcomes)
    if not frame.empty:
        frame["entry_dt"] = pd.to_datetime(frame["entry_ms"], unit="ms", utc=True)
        frame["entry_year"] = frame["entry_dt"].dt.year
    return frame


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("/mnt/data"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    market = base.load_market(args.data_root)
    prepared = {
        symbol: base.prepare_5m(market[symbol]["5m"]) for symbol in base.SYMBOLS
    }
    data = base.arrays(market, prepared)
    candidates: list[base.EventCandidate] = []
    for symbol in base.SYMBOLS:
        candidates.extend(base.build_candidates(symbol, prepared[symbol]))

    annual_rows: list[dict[str, Any]] = []
    action_year_counts: dict[str, int] = {}
    for year in base.YEARS:
        start = int(pd.Timestamp(f"{year}-01-01", tz="UTC").timestamp() * 1000)
        boundary = int(
            pd.Timestamp(f"{year + 1}-01-01", tz="UTC").timestamp() * 1000
        )
        frame = _simulate_candidates(candidates, data, boundary, start)
        frame = frame[frame["entry_year"].eq(year)].copy()
        for action in ("ACCEPT", "REJECT"):
            action_year_counts[f"{action}_{year}"] = int(frame["action"].eq(action).sum())
            for row in evaluate_source(frame, action=action, period=str(year)):
                row["year"] = year
                annual_rows.append(row)

    annual = pd.DataFrame(annual_rows)
    annual.to_csv(args.output / "ACTION_YEAR_COST_GRID.csv", index=False)

    continuous_frame = _simulate_candidates(candidates, data, PRE2024_BOUNDARY_MS)
    continuous_rows: list[dict[str, Any]] = []
    for action in ("ACCEPT", "REJECT"):
        continuous_rows.extend(
            evaluate_source(continuous_frame, action=action, period="2021_2023")
        )
    continuous = pd.DataFrame(continuous_rows)
    continuous.to_csv(args.output / "CONTINUOUS_PRE2024_GRID.csv", index=False)

    raw = continuous_frame.groupby(["action", "entry_year"]).agg(
        events=("event_id", "count"),
        gross_mean=("gross_fraction", "mean"),
        gross_median=("gross_fraction", "median"),
        funding_mean=("funding_fraction", "mean"),
        stop_median=("stop_fraction", "median"),
        hold_median_min=("holding_min", "median"),
        marked=("completed", lambda values: int((~values.astype(bool)).sum())),
    ).reset_index()
    raw.to_csv(args.output / "RAW_ACTION_STATS.csv", index=False)

    result = {
        "schema_version": 2,
        "result_id": "RES-20260730-PRIOR-DAY-LIQUIDITY-INTERACTION-FATAL-001",
        "claim_id": "CLM-20260729-ML-LIQUIDITY-INTERACTION-AV-001",
        "status": "RETIRED_EXACT_PRIOR_DAY_INTERACTION_FATAL_SCREEN",
        "scope": "prior completed UTC-day high/low interaction; two-close acceptance continuation versus first-close rejection reversal",
        "programization_correction": {
            "id": CORRECTION_ID,
            "defect": "annual diagnostics could omit unresolved exposure or value an entry-year trade at a later-year structural exit",
            "corrected_rule": "search exits only before each UTC boundary; mark unresolved exposure at the last observed pre-boundary minute; fund through the boundary; retain slot occupation; never assert a boundary strategy close",
            "economic_verdict_changed": False,
        },
        "candidate_counts": {
            "total_generated": len(candidates),
            "evaluable_pre2024": len(continuous_frame),
            "by_action_year": action_year_counts,
        },
        "annual_grid_file": "ACTION_YEAR_COST_GRID.csv",
        "continuous_grid_file": "CONTINUOUS_PRE2024_GRID.csv",
        "raw_action_stats_file": "RAW_ACTION_STATS.csv",
        "data": {
            f"{symbol}_{year}": {
                "file": base.source_path(args.data_root, symbol, year).name,
                "sha256": _hash(base.source_path(args.data_root, symbol, year)),
            }
            for symbol in base.SYMBOLS
            for year in base.YEARS
        },
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    (args.output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
