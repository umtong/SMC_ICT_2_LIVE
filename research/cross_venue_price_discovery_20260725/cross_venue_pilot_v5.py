from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import cross_venue_pilot as v1
import cross_venue_pilot_v2 as v2
import cross_venue_execution_v5 as v5

FEE_LEVELS = (0.0, 5.0, 7.5, 10.0)


def run(output: Path, cache: Path, days: tuple[str, ...] = v1.PILOT_DAYS) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    v5.patch_v5()
    v2.LATENCY_DIAGNOSTICS.clear()
    configs = v1.pilot_grid()
    gross_trades: dict[str, list[v5.FixedTradeV5]] = {config.config_id: [] for config in configs}
    event_counts: dict[str, int] = {config.config_id: 0 for config in configs}
    source_records: list[dict] = []

    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-venue-pilot-v5/1.0"
        for day in days:
            frames: dict[tuple[str, str], pd.DataFrame] = {}
            for symbol in v1.SYMBOLS:
                frame, records = v1.load_day(cache, session, day, symbol)
                frames[(day, symbol)] = frame
                source_records.extend(records)
                print(json.dumps({"stage": "pilot_v5_load", "day": day, "symbol": symbol, "rows": len(frame)}), flush=True)
            for number, config in enumerate(configs, 1):
                events: list[v1.Event] = []
                for (event_day, symbol), frame in frames.items():
                    events.extend(v2.signal_events_v2(frame, config, event_day, symbol))
                event_counts[config.config_id] += len(events)
                gross_trades[config.config_id].extend(v5.simulate_fixed_day_v5(frames, events, config))
                if number % 50 == 0:
                    print(json.dumps({
                        "stage": "pilot_v5_simulation",
                        "day": day,
                        "configs_done": number,
                        "configs_total": len(configs),
                    }), flush=True)

    rows: list[dict] = []
    ledgers: list[pd.DataFrame] = []
    for config in configs:
        base_trades = gross_trades[config.config_id]
        for fee in FEE_LEVELS:
            trades = v5.apply_fixed_fee(base_trades, fee)
            summary = v1.metrics(trades)
            rows.append({
                "config_id": config.config_id,
                **asdict(config),
                "fee_bps_per_side": fee,
                "event_count": event_counts[config.config_id],
                **{key: value for key, value in summary.items() if not isinstance(value, dict)},
            })
            if fee == 5.0 and trades:
                ledger = pd.DataFrame([asdict(item) for item in trades])
                ledger["config_id"] = config.config_id
                ledgers.append(ledger)

    grid = pd.DataFrame(rows)
    grid.to_csv(output / "PILOT_GRID.csv", index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(output / "PILOT_5BPS_LEDGERS.csv", index=False)

    base = grid.loc[grid.fee_bps_per_side == 5.0].copy()
    zero = grid.loc[grid.fee_bps_per_side == 0.0, [
        "config_id", "mean_net_bps", "total_fixed_notional_return",
    ]].rename(columns={
        "mean_net_bps": "zero_fee_mean_bps",
        "total_fixed_notional_return": "zero_fee_total_return",
    })
    stress = grid.loc[grid.fee_bps_per_side == 10.0, [
        "config_id", "mean_net_bps", "total_fixed_notional_return",
    ]].rename(columns={
        "mean_net_bps": "ten_fee_mean_bps",
        "total_fixed_notional_return": "ten_fee_total_return",
    })
    candidates = base.merge(zero, on="config_id").merge(stress, on="config_id")
    candidates["fatal_edge_pass"] = (
        (candidates.n >= 100)
        & (candidates.zero_fee_mean_bps > 0)
        & (candidates.total_fixed_notional_return > 0)
        & (candidates.ten_fee_total_return > 0)
        & (candidates.top10pct_removed_mean_bps > 0)
        & (candidates.positive_day_fraction >= 0.50)
    )
    candidates = candidates.sort_values(
        ["fatal_edge_pass", "ten_fee_total_return", "config_id"],
        ascending=[False, False, True],
    )
    candidates.to_csv(output / "PILOT_CANDIDATES.csv", index=False)

    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-1850-XVENUE-001",
        "stage": "MICROSECOND_LOCAL_ARRIVAL_FATAL_EDGE_PILOT_V5",
        "causal_version": v5.CAUSAL_VERSION,
        "availability_clock": "local_timestamp_microsecond",
        "bucket_availability": "completed_100ms",
        "entry_contract": "first adverse actual Binance quote group at or after aligned decision plus latency",
        "exit_contract": "completed-bucket stop/convergence/horizon trigger plus configured latency and mandatory adverse exit",
        "portfolio_order": "actual_first_executable_local_arrival_then_known_score",
        "pilot_days": list(days),
        "configurations": len(configs),
        "fatal_edge_pass_count": int(candidates.fatal_edge_pass.sum()),
        "best": candidates.iloc[0].replace({np.nan: None}).to_dict() if len(candidates) else None,
        "development_opened": False,
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "ranking_eligible": False,
        "v1_v2_v3_v4_v4b_outputs_admissible": False,
        "source_records": source_records,
        "source_latency_diagnostics": v2.LATENCY_DIAGNOSTICS,
    }
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
        "causal_version": result["causal_version"],
        "fatal_edge_pass_count": result["fatal_edge_pass_count"],
        "best": result["best"],
        "development_opened": False,
        "2026_opened": False,
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
