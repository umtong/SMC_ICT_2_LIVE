from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import requests

import tardis_pilot as pilot
import tardis_development_v2 as development
import tardis_selection_v2 as selection

CONFIRMATION_DAYS = tuple(f"2025-{month:02d}-01" for month in range(1, 13))
FEE_LEVELS = development.FEE_LEVELS


def confirmation_pass(by_fee: dict[float, dict]) -> bool:
    base = by_fee[5.0]
    return (
        base["n"] >= 200
        and all(by_fee[fee]["total_return"] > 0 for fee in FEE_LEVELS)
        and base["positive_day_fraction"] >= 0.58
        and (base["top10pct_removed_return"] is not None and base["top10pct_removed_return"] > 0)
        and (base["profit_factor"] is not None and base["profit_factor"] >= 1.05)
        and base["maximum_drawdown"] <= 0.20
        and base["maximum_single_asset_positive_pnl_share"] <= 0.70
    )


def run(predecessor: Path, output: Path, cache: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    raw = predecessor.read_bytes()
    wrapper = json.loads(raw)
    selected = wrapper.get("selection")
    if wrapper.get("status") != "SELECTION_PASS" or not selected:
        result = {"schema_version": 2, "claim_id": "CLM-20260725-2120-CROSS-MARGIN-001", "stage": "CONFIRMATION_BLOCKED_BY_SELECTION_GATE", "predecessor_sha256": hashlib.sha256(raw).hexdigest(), "confirmation_opened": False, "sample_confirmation_pass": False, "target_1pct_daily_test_admissible": False, "target_1pct_daily_pass": False, "2026_opened": False, "orders_submitted": False, "paper_live_started": False, "champion_eligible": False}
        (output / "CONFIRMATION_RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result
    primary = selected.get("frozen_primary")
    if int(selected.get("selection_gate_pass_count", 0)) <= 0 or not primary:
        raise ValueError("SELECTION_PASS wrapper has no frozen primary")
    config = pilot.Config(**primary["config"])
    frames = {}
    sources = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-margin-confirmation/1.0"
        for day in CONFIRMATION_DAYS:
            for asset in pilot.ROUTES:
                frame, records = pilot.load_day(cache, session, day, asset)
                frames[(day, asset)] = frame
                sources.extend(records)
                print(json.dumps({"day": day, "asset": asset, "aligned_rows": len(frame)}), flush=True)
    events = []
    for (day, asset), frame in frames.items():
        events.extend(pilot.signals(frame, config, day, asset))
    by_fee = {}
    ledgers = []
    for fee in FEE_LEVELS:
        trades, state = development.simulate_account(frames, events, config, fee)
        metrics = selection.metrics_for_days(trades, state, CONFIRMATION_DAYS)
        by_fee[fee] = metrics
        if trades:
            ledger = pd.DataFrame([asdict(item) for item in trades])
            ledger["fee_bps_per_side"] = fee
            ledgers.append(ledger)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(output / "CONFIRMATION_LEDGERS.csv", index=False)
    passed = confirmation_pass(by_fee)
    result = {
        "schema_version": 2,
        "claim_id": "CLM-20260725-2120-CROSS-MARGIN-001",
        "dataset_revision": "TARDIS_PUBLIC_NORMALIZED_SAMPLE_V1",
        "stage": "FROZEN_2025_SYSTEMATIC_SAMPLE_CONFIRMATION",
        "predecessor_sha256": hashlib.sha256(raw).hexdigest(),
        "primary": primary,
        "confirmation_days": list(CONFIRMATION_DAYS),
        "confirmation_opened": True,
        "sample_confirmation_pass": passed,
        "metrics": {str(fee): by_fee[fee] for fee in FEE_LEVELS},
        "full_tick_dataset_required_before_target_test": passed,
        "target_1pct_daily_test_admissible": False,
        "target_1pct_daily_pass": False,
        "reason_target_not_admissible": "Systematic monthly first-day samples omit most operable days and cannot establish full-calendar geometric daily NAV growth.",
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "champion_eligible": False,
        "source_records": sources,
    }
    path = output / "CONFIRMATION_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    (output / "CONFIRMATION_RESULT.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.predecessor, args.output, args.cache)
    print(json.dumps({"stage": result["stage"], "confirmation_opened": result["confirmation_opened"], "sample_confirmation_pass": result.get("sample_confirmation_pass", False), "target_1pct_daily_test_admissible": False, "2026_opened": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
