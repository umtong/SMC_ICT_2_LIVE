from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

import cross_venue_counterfactual_v5d as counterfactual
import cross_venue_development_v2 as d2
import cross_venue_development_v5 as development
import cross_venue_execution_v5d as v5d
import cross_venue_pilot as v1

BASE_FEE = counterfactual.BASE_FEE
FEE_LEVELS = development.FEE_LEVELS


def validate_pilot_v5d(pilot_dir: Path) -> dict:
    result = json.loads((pilot_dir / "PILOT_RESULT.json").read_text(encoding="utf-8"))
    if result.get("causal_version") != v5d.CAUSAL_VERSION:
        raise ValueError("pilot causal version is not V5")
    if result.get("causal_engine_version") != v5d.ENGINE_VERSION:
        raise ValueError("pilot did not use the V5D engine")
    if result.get("v1_v2_v3_v4_v4b_v5_v5b_v5c_outputs_admissible") is not False:
        raise ValueError("pilot did not block all earlier engines")
    required = (
        "funding_boundary_contract",
        "protective_stop_contract",
        "source_continuity_contract",
        "execution_gap_contract",
        "exit_floor_contract",
        "drawdown_contract",
    )
    if any(not result.get(key) for key in required):
        raise ValueError("pilot is missing a frozen V5D validity contract")
    if result.get("pilot_day_denominator") != "all preregistered pilot dates including zero-trade dates":
        raise ValueError("pilot day denominator is incomplete")
    return result


def preliminary_pass(metrics_by_fee: dict[float, dict]) -> bool:
    base = metrics_by_fee[BASE_FEE]
    return (
        not bool(base.get("terminal_account_loss", False))
        and base["n"] >= 500
        and base["trades_per_day_median"] >= 10
        and all(metrics_by_fee[fee]["total_return"] > 0 for fee in FEE_LEVELS)
        and base["return_2022"] > 0
        and base["return_2023"] > 0
        and base["positive_day_fraction"] >= 0.60
        and base["top5_positive_share"] <= 0.20
        and (base["profit_factor"] is not None and base["profit_factor"] >= 1.10)
        and base["maximum_drawdown"] <= 0.20
        and base["maximum_single_symbol_positive_pnl_share"] <= 0.70
    )


def _update_grid(output: Path, selections: list[dict]) -> None:
    path = output / "DEVELOPMENT_GRID.csv"
    if not path.exists():
        return
    grid = pd.read_csv(path)
    grid["top10_counterfactual_status"] = "NOT_RUN"
    for item in selections:
        metrics = item["metrics"][str(BASE_FEE)]
        mask = (grid.config_id.astype(str) == str(item["config_id"])) & (grid.fee_bps_per_side == BASE_FEE)
        grid.loc[mask, "top10pct_removed_return"] = metrics.get("top10pct_removed_return")
        grid.loc[mask, "top10_counterfactual_status"] = metrics.get("top10_counterfactual_status")
    grid.to_csv(path, index=False)


def run(pilot_dir: Path, output: Path, cache: Path) -> dict:
    validate_pilot_v5d(pilot_dir)
    v5d.patch_v5()
    original_passes = d2.passes
    d2.passes = preliminary_pass
    try:
        result = development.run(pilot_dir, output, cache)
    finally:
        d2.passes = original_passes

    ledger_path = output / "DEVELOPMENT_5BPS_LEDGERS.csv"
    ledgers = pd.read_csv(ledger_path) if ledger_path.exists() else pd.DataFrame()
    selections = list(result.get("family_selections", []))
    for item in selections:
        metrics = item["metrics"][str(BASE_FEE)]
        preliminary = bool(item.get("development_pass", False))
        metrics["preliminary_gate_pass_without_top10"] = preliminary
        if not preliminary:
            item["development_pass"] = False
            metrics["top10pct_removed_return"] = None
            metrics["top10_counterfactual_status"] = "NOT_RUN_BECAUSE_OTHER_GATES_FAILED"
            continue
        subset = ledgers.loc[ledgers.config_id.astype(str) == str(item["config_id"])].copy()
        if subset.empty:
            raise ValueError("V5D preliminary survivor has no 5-bps ledger")
        removed = counterfactual.winner_keys(subset)
        exact = counterfactual.replay_without_events(v1.Config(**item["config"]), removed, cache)
        metrics["top10pct_removed_return"] = exact
        metrics["top10_counterfactual_status"] = "RERUN_FROM_INITIAL_NAV_WITH_SLOT_RELEASE"
        metrics["top10_counterfactual_removed_trade_count"] = len(removed)
        item["development_pass"] = exact > 0

    passed = [item for item in selections if item.get("development_pass", False)]
    passed.sort(
        key=lambda item: min(
            item["metrics"]["5.0"]["return_2022"],
            item["metrics"]["5.0"]["return_2023"],
            item["metrics"]["7.5"]["total_return"],
            item["metrics"]["10.0"]["total_return"],
            item["metrics"]["5.0"]["top10pct_removed_return"],
        ),
        reverse=True,
    )
    result.update({
        "stage": "MICROSECOND_LOCAL_ARRIVAL_RISK_BASED_DEVELOPMENT_V5D",
        "causal_engine_version": v5d.ENGINE_VERSION,
        "account_engine_version": v5d.ENGINE_VERSION,
        "family_selections": selections,
        "development_gate_pass_count": len(passed),
        "frozen_development_representatives": passed[:12],
        "counterfactual_top10_contract": "remove baseline top-10% event keys before slot competition and rerun from initial NAV",
        "source_continuity_contract": "segmented rolling state resets after unavailable Binance/Bybit state",
        "execution_gap_contract": "entry and exit quotes within 1s; finite state throughout accepted positions",
        "exit_floor_contract": "no economic 10%-of-quote floor; numerical positive floor only",
        "drawdown_contract": "single chronological marked account path without double counting",
        "v1_v2_v3_v4_v4b_v5_v5b_v5c_promotion_admissible": False,
        "ranking_eligible": False,
    })
    _update_grid(output, selections)
    path = output / "DEVELOPMENT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (output / "DEVELOPMENT_RESULT.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8"
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
