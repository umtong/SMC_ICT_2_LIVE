from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from core import PriceSeries, inclusive_calendar_days, month_starts, write_json
from data import (
    aggregate_liquidations, build_features, download_period_sources, load_klines,
    load_liquidations, make_price_series, threshold_table,
)
from engine import (
    evaluate_candidates, generate_candidates, select_signals, simulate_account,
)

# Public re-exports used by the causal invariant tests.
__all__ = [
    "PriceSeries", "aggregate_liquidations", "build_features",
    "generate_candidates", "simulate_account", "run",
]

def run(prereg_path: Path, output: Path, cache: Path) -> dict[str, Any]:
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    shutil.copy2(prereg_path, output / "preregistration.json")
    assets = [str(x) for x in prereg["assets"]]
    periods = prereg["periods"]
    fit_dates = month_starts(periods["fit"]["from"], periods["fit"]["to"])
    dev_dates = month_starts(periods["development"]["from"], periods["development"]["to"])
    discovery_dates = fit_dates + dev_dates

    records, liq_paths, kline_paths = download_period_sources(discovery_dates, assets, cache)
    liquidations = load_liquidations(liq_paths, assets)
    klines = load_klines(kline_paths)
    fit_liq = liquidations.loc[liquidations["source_date"].isin({d.isoformat() for d in fit_dates})]
    dev_liq = liquidations.loc[liquidations["source_date"].isin({d.isoformat() for d in dev_dates})]
    fit_features, fit_positive = build_features(fit_liq, klines, fit_dates, assets)
    dev_features, _ = build_features(dev_liq, klines, dev_dates, assets)
    thresholds = threshold_table(
        fit_positive, [float(x) for x in prereg["candidate_grid"]["liquidation_quantile"]]
    )
    candidates = generate_candidates(prereg)
    price_series = make_price_series(klines)
    candidate_results, _ = evaluate_candidates(
        candidates, fit_features, dev_features, thresholds, price_series, prereg
    )
    candidate_results.to_csv(output / "candidate_results.csv", index=False)
    write_json(output / "fit_thresholds.json", thresholds)
    write_json(output / "source_manifest.json", [record.as_dict() for record in records])
    survivors = candidate_results.loc[candidate_results["development_gate_pass"] == True].copy()  # noqa: E712
    nonzero = candidate_results.loc[candidate_results["dev18_trade_count"] > 0]
    best_raw = (nonzero.iloc[0] if not nonzero.empty else candidate_results.iloc[0]).to_dict()
    best_raw_params = dict(
        next(candidate for candidate in candidates if candidate["candidate_id"] == best_raw["candidate_id"])
    )
    for label, features, period in (
        ("fit", fit_features, periods["fit"]),
        ("dev", dev_features, periods["development"]),
    ):
        signals = select_signals(features, best_raw_params, thresholds)
        _, trades = simulate_account(
            signals,
            best_raw_params,
            price_series,
            initial_nav=float(prereg["account"]["initial_nav"]),
            risk_fraction=float(prereg["account"]["risk_fraction"]),
            cost_bps=float(prereg["account"]["primary_cost_bps"]),
            calendar_days=inclusive_calendar_days(period),
            observed_days=len(month_starts(period["from"], period["to"])),
        )
        trades.to_csv(output / f"best_raw_{label}_trades_18bps.csv", index=False)
    validation_opened = False
    selected_payload: dict[str, Any] | None = None
    validation_metrics: dict[str, Any] | None = None

    if not survivors.empty:
        selected = survivors.iloc[0].to_dict()
        selected_params = dict(
            next(
                candidate
                for candidate in candidates
                if candidate["candidate_id"] == selected["candidate_id"]
            )
        )
        selected_payload = {
            "selected_candidate": selected_params,
            "development_metrics": selected,
            "selection_rule": "highest preregistered selection_score among full development-gate survivors",
        }
        write_json(output / "selected_candidate.json", selected_payload)

        # Only a full preregistered development survivor is allowed to open 2024 public sample outcomes.
        validation_dates = month_starts(periods["validation"]["from"], periods["validation"]["to"])
        val_records, val_liq_paths, val_kline_paths = download_period_sources(validation_dates, assets, cache)
        records.extend(val_records)
        write_json(output / "source_manifest.json", [record.as_dict() for record in records])
        val_liq = load_liquidations(val_liq_paths, assets)
        val_klines = load_klines(val_kline_paths)
        val_features, _ = build_features(val_liq, val_klines, validation_dates, assets)
        val_signals = select_signals(val_features, selected_params, thresholds)
        validation_metrics = {}
        val_series = make_price_series(val_klines)
        for cost in prereg["account"]["cost_stress_round_trip_bps"]:
            metrics, trades = simulate_account(
                val_signals,
                selected_params,
                val_series,
                initial_nav=float(prereg["account"]["initial_nav"]),
                risk_fraction=float(prereg["account"]["risk_fraction"]),
                cost_bps=float(cost),
                calendar_days=inclusive_calendar_days(periods["validation"]),
                observed_days=len(validation_dates),
            )
            validation_metrics[str(cost)] = metrics
            trades.to_csv(output / f"validation_trades_{int(float(cost))}bps.csv", index=False)
        validation_opened = True
        write_json(output / "validation_metrics.json", validation_metrics)

    best_growth = float(best_raw["dev18_geometric_daily_growth_observed_days"])
    status = "PROMISING_COMPONENT" if validation_opened else "TESTED_BELOW_GATE"
    summary = {
        "study_id": prereg["study_id"],
        "claim_id": prereg["claim_id"],
        "status": status,
        "hard_validity": "PASS",
        "candidate_count": int(len(candidate_results)),
        "development_gate_count": int(len(survivors)),
        "validation_opened": bool(validation_opened),
        "confirmation_2025_opened": False,
        "final_2026_opened": False,
        "best_raw_candidate_id": str(best_raw["candidate_id"]),
        "best_raw_family": str(best_raw["family"]),
        "best_raw_dev_trade_count_18bps": int(best_raw["dev18_trade_count"]),
        "best_raw_dev_total_return_18bps": float(best_raw["dev18_total_return"]),
        "best_raw_dev_observed_day_growth_18bps": best_growth,
        "best_raw_dev_calendar_growth_18bps": float(
            best_raw["dev18_geometric_daily_growth_calendar"]
        ),
        "best_raw_dev_top10_removed_return_18bps": float(
            best_raw["dev18_top10_removed_return"]
        ),
        "best_raw_dev_total_return_24bps": float(best_raw["dev24_total_return"]),
        "selected_candidate": selected_payload,
        "validation_metrics": validation_metrics,
        "component_observed_day_target_exceeded": bool(best_growth >= 0.01),
        "official_target_met": False,
        "first_place_eligible": False,
        "first_place_changed": False,
        "orders_submitted": False,
        "paper_live_enabled": False,
        "bybit_replication_complete": False,
        "promotion_boundary": prereg["promotion_boundary"],
        "known_source_limitation": prereg["information_boundary"]["known_source_limitation"],
    }
    write_json(output / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Causal liquidation-refill event study")
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run(args.preregistration, args.output, args.cache)
    print(json.dumps(summary, sort_keys=True, default=str), flush=True)

if __name__ == "__main__":
    main()
