from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

CLAIM_ID = "CLM-20260730-REJECTION-BLOCK-100MS-TAKEOVER-001"
RESULT_ID = "RES-20260730-REJECTION-BLOCK-100MS-CORRECTED-001"
SUPERSEDED_RESULT_ID = "RES-20260726-REJECTION-BLOCK-FATAL-001"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def best_eventful(frame: pd.DataFrame, cost: int) -> dict[str, Any] | None:
    trades_col = f"cost_{cost}_trades"
    mean_col = f"cost_{cost}_mean_net_bps"
    median_col = f"cost_{cost}_median_net_bps"
    pf_col = f"cost_{cost}_profit_factor"
    multiple_col = f"cost_{cost}_unlevered_multiple"
    eventful = frame[frame[trades_col] > 0].copy()
    if eventful.empty:
        return None
    row = eventful.sort_values(
        [mean_col, median_col, trades_col, "candidate_id"],
        ascending=[False, False, False, True],
    ).iloc[0]
    return {
        "candidate_id": str(row.candidate_id),
        "bar_seconds": int(row.bar_seconds),
        "liquidity_lookback_seconds": int(row.liquidity_lookback_seconds),
        "raid_excess_bps": float(row.raid_excess_bps),
        "minimum_wick_body_ratio": float(row.minimum_wick_body_ratio),
        "confirm_displacement_bps": float(row.confirm_displacement_bps),
        "entry_fraction": float(row.entry_fraction),
        "trades": int(row[trades_col]),
        "mean_net_bps": float(row[mean_col]),
        "median_net_bps": float(row[median_col]),
        "profit_factor": float(row[pf_col]),
        "unlevered_multiple": float(row[multiple_col]),
        "terminal_marked_events": int(row.terminal_marked_event_count),
    }


def cost_summary(frame: pd.DataFrame, cost: int) -> dict[str, Any]:
    trades_col = f"cost_{cost}_trades"
    mean_col = f"cost_{cost}_mean_net_bps"
    median_col = f"cost_{cost}_median_net_bps"
    pf_col = f"cost_{cost}_profit_factor"
    multiple_col = f"cost_{cost}_unlevered_multiple"
    eventful = frame[frame[trades_col] > 0].copy()
    return {
        "eventful_candidate_count": int(len(eventful)),
        "maximum_trades_per_candidate": int(eventful[trades_col].max()) if len(eventful) else 0,
        "positive_mean_candidate_count": int((eventful[mean_col] > 0).sum()),
        "positive_median_candidate_count": int((eventful[median_col] > 0).sum()),
        "profit_factor_above_one_candidate_count": int((eventful[pf_col] > 1.0).sum()),
        "maximum_mean_net_bps": float(eventful[mean_col].max()) if len(eventful) else 0.0,
        "maximum_median_net_bps": float(eventful[median_col].max()) if len(eventful) else 0.0,
        "maximum_profit_factor": float(eventful[pf_col].max()) if len(eventful) else 0.0,
        "maximum_unlevered_multiple": float(eventful[multiple_col].max()) if len(eventful) else 1.0,
        "best_eventful_candidate": best_eventful(frame, cost),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen-output", type=Path, required=True)
    parser.add_argument("--patch-result", type=Path, required=True)
    parser.add_argument("--patch-diff", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    archived = json.loads((args.screen_output / "RESULT.json").read_text(encoding="utf-8"))
    frozen = json.loads((args.screen_output / "FROZEN_SELECTION.json").read_text(encoding="utf-8"))
    patch = json.loads(args.patch_result.read_text(encoding="utf-8"))
    fit = pd.read_csv(args.screen_output / "fit_screen.csv")

    if len(fit) != 216 or int(archived["candidate_count"]) != 216:
        raise SystemExit("frozen candidate count changed")
    if patch.get("replacement_count") != 2:
        raise SystemExit("source-frequency patch was not exactly two replacements")
    if archived.get("2024_opened") is not False or archived.get("2025_or_2026_opened") is not False:
        raise SystemExit("prohibited official period was opened")
    if archived.get("orders_submitted") is not False:
        raise SystemExit("unexpected order submission")

    fit_survivors = int(fit.fit_gate.astype(bool).sum())
    eventful = fit[fit.cost_24_trades > 0]
    development_opened = bool(frozen.get("development_opened"))
    if development_opened != (fit_survivors > 0):
        raise SystemExit("conditional development boundary mismatch")

    costs = {str(cost): cost_summary(fit, cost) for cost in (12, 18, 24)}
    scarcity = {
        "candidate_count": int(len(fit)),
        "eventful_candidate_count": int(len(eventful)),
        "maximum_raw_events_per_candidate": int(fit.raw_event_count.max()),
        "maximum_completed_trades_per_candidate": int(fit.cost_24_trades.max()),
        "frozen_minimum_fit_trades": 12,
        "fit_survivor_count": fit_survivors,
        "development_opened": development_opened,
    }

    if fit_survivors == 0:
        status = "RETIRED_CORRECTED_SOURCE_FREQUENCY_ECONOMIC_SCARCITY_AND_NEGATIVE_EDGE"
        next_action = (
            "Retire this exact terminal-wick Rejection Block family. Do not tune the frozen 216 cells, "
            "cost, risk, leverage, session, target or confirmation thresholds; change the primary economic information unit."
        )
    else:
        status = "FIT_SURVIVOR_CONDITIONAL_DEVELOPMENT_COMPLETED"
        next_action = "Inspect the unchanged development result before any current-contract or official-period expansion."

    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "result_id": RESULT_ID,
        "supersedes_hard_invalid_result_id": SUPERSEDED_RESULT_ID,
        "status": status,
        "hard_validity_status": "PASS_EXACT_ARCHIVED_EVALUATOR_WITH_TWO_SOURCE_FREQUENCY_CORRECTIONS",
        "economic_status": "BELOW_GATE" if fit_survivors == 0 else "CONDITIONAL_DEVELOPMENT_EVALUATED",
        "rank_eligible": False,
        "ranking_change": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
        "frozen_scope": {
            "venue": "Bybit",
            "instrument": "BTCUSDT linear perpetual",
            "fit_date": "2022-07-01",
            "conditional_development_date": "2023-07-01",
            "candidate_count": 216,
            "source_state_frequency_ms": 100,
            "strategy_or_account_parameter_changes": 0,
        },
        "patch": {
            **patch,
            "diff_sha256": file_sha256(args.patch_diff),
        },
        "scarcity": scarcity,
        "cost_summaries": costs,
        "next_action": next_action,
        "source_screen_result_sha256": file_sha256(args.screen_output / "RESULT.json"),
        "fit_screen_sha256": file_sha256(args.screen_output / "fit_screen.csv"),
    }

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    eventful.sort_values(
        ["cost_24_mean_net_bps", "cost_24_trades", "candidate_id"],
        ascending=[False, False, True],
    ).to_csv(args.output / "EVENTFUL_FIT_CANDIDATES.csv", index=False)

    report = f"""# Corrected 100 ms ICT Rejection Block result

## Decision

`{RESULT_ID}` is **{status}**.

The archived PR #102 result was hard-invalid because a 100 ms source was treated as 500 ms. This takeover reconstructed the SHA-bound evaluator and changed exactly two source-cadence assumptions, with no strategy, candidate, date, cost, risk, leverage, target, or account change.

## Frozen fit result

- candidate cells: {scarcity['candidate_count']}
- candidates with at least one completed 24 bp trade: {scarcity['eventful_candidate_count']}
- maximum trades in any candidate: {scarcity['maximum_completed_trades_per_candidate']}
- frozen minimum required trades: {scarcity['frozen_minimum_fit_trades']}
- fit survivors: {scarcity['fit_survivor_count']}
- conditional 2023 development opened: {str(scarcity['development_opened']).lower()}

At 12/18/24 bp, the number of candidates with positive mean return was {costs['12']['positive_mean_candidate_count']} / {costs['18']['positive_mean_candidate_count']} / {costs['24']['positive_mean_candidate_count']}. The best eventful 24 bp candidate still had mean {costs['24']['maximum_mean_net_bps']:.6f} bp, median {costs['24']['maximum_median_net_bps']:.6f} bp, PF {costs['24']['maximum_profit_factor']:.6f}, and at most {costs['24']['maximum_trades_per_candidate']} trades.

## Interpretation

The programization defect was real: correcting source cadence restored events. It did not restore a tradable edge. The exact family is both too sparse for its frozen gate and negative even before any risk or leverage search. Calendar 2023 remained sealed because no fit survivor existed; official 2024-2026 remained unopened.

## Boundary

No adjacent tuning, ML rescue, risk/leverage search, credentials, paper orders, or live orders were used.
"""
    (args.output / "REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
