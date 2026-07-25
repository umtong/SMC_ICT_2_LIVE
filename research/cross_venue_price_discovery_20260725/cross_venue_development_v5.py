from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import requests

import cross_venue_pilot as v1
import cross_venue_pilot_v2 as v2
import cross_venue_development_v2 as d2
import cross_venue_execution_v5 as v5

PILOT_DAYS = set(v1.PILOT_DAYS)
DEVELOPMENT_DAYS = tuple(
    f"{year}-{month:02d}-01"
    for year in (2022, 2023)
    for month in range(1, 13)
    if f"{year}-{month:02d}-01" not in PILOT_DAYS
)
FEE_LEVELS = d2.FEE_LEVELS


def _config_from_row(row: pd.Series) -> v1.Config:
    return v1.Config(
        str(row.family),
        int(row.observation_ms),
        float(row.displacement_spreads),
        float(row.flow_imbalance),
        float(row.follower_fraction),
        int(row.latency_ms),
        int(row.hold_ms),
        float(row.stop_spreads),
        float(row.basis_z),
    )


def freeze_pilot_representatives(pilot_dir: Path, output: Path) -> list[v1.Config]:
    source = pilot_dir / "PILOT_RESULT.json"
    raw = source.read_bytes()
    result = json.loads(raw)
    if result.get("causal_version") != v5.CAUSAL_VERSION:
        raise ValueError("pilot is not authoritative causal V5")
    if result.get("v1_v2_v3_v4_v4b_outputs_admissible") is not False:
        raise ValueError("pilot did not explicitly invalidate earlier engines")
    table = pd.read_csv(pilot_dir / "PILOT_CANDIDATES.csv")
    raw_flag = table.fatal_edge_pass
    if raw_flag.dtype == object:
        flag = raw_flag.astype(str).str.lower().eq("true")
    else:
        flag = raw_flag.astype(bool)
    passed = table.loc[flag].copy()
    chosen: list[pd.Series] = []
    if not passed.empty:
        passed = passed.sort_values(
            ["ten_fee_total_return", "top10pct_removed_mean_bps", "config_id"],
            ascending=[False, False, True],
        )
        used: set[str] = set()
        for _, row in passed.groupby(["family", "latency_ms"], sort=True).head(1).iterrows():
            config_id = str(row.config_id)
            if config_id not in used:
                chosen.append(row)
                used.add(config_id)
        for _, row in passed.iterrows():
            if len(chosen) >= 12:
                break
            config_id = str(row.config_id)
            if config_id not in used:
                chosen.append(row)
                used.add(config_id)
    configs = [_config_from_row(row) for row in chosen[:12]]
    payload = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-1850-XVENUE-001",
        "causal_version": v5.CAUSAL_VERSION,
        "source_pilot_sha256": hashlib.sha256(raw).hexdigest(),
        "pilot_fatal_edge_pass_count": int(result["fatal_edge_pass_count"]),
        "representatives": [asdict(config) | {"config_id": config.config_id} for config in configs],
        "development_days": list(DEVELOPMENT_DAYS),
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "v1_v2_v3_v4_v4b_promotion_admissible": False,
    }
    path = output / "FROZEN_PILOT_REPRESENTATIVES_V5.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "FROZEN_PILOT_REPRESENTATIVES_V5.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
        encoding="utf-8",
    )
    return configs


def run(pilot_dir: Path, output: Path, cache: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    v5.patch_v5()
    configs = freeze_pilot_representatives(pilot_dir, output)
    if not configs:
        result = {
            "schema_version": 1,
            "claim_id": "CLM-20260725-1850-XVENUE-001",
            "stage": "DEVELOPMENT_BLOCKED_BY_FATAL_PILOT_V5",
            "causal_version": v5.CAUSAL_VERSION,
            "development_opened": False,
            "development_gate_pass_count": 0,
            "selection_opened": False,
            "confirmation_opened": False,
            "2026_opened": False,
            "orders_submitted": False,
            "paper_live_started": False,
            "ranking_eligible": False,
            "v1_v2_v3_v4_v4b_promotion_admissible": False,
            "reason": "No causal V5 pilot configuration passed the fatal edge gate.",
        }
        path = output / "DEVELOPMENT_RESULT.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    trade_store: dict[tuple[str, float], list[v5.AccountTradeV5]] = {
        (config.config_id, fee): [] for config in configs for fee in FEE_LEVELS
    }
    state_store: dict[tuple[str, float], dict[str, float]] = {
        (config.config_id, fee): v5.initial_account_state() for config in configs for fee in FEE_LEVELS
    }
    event_counts: dict[str, int] = {config.config_id: 0 for config in configs}
    source_records: list[dict] = []
    v2.LATENCY_DIAGNOSTICS.clear()

    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-venue-development-v5/1.0"
        for day in DEVELOPMENT_DAYS:
            frames: dict[tuple[str, str], pd.DataFrame] = {}
            for symbol in v1.SYMBOLS:
                frame, records = v1.load_day(cache, session, day, symbol)
                frames[(day, symbol)] = frame
                source_records.extend(records)
                print(json.dumps({"stage": "development_v5_load", "day": day, "symbol": symbol, "rows": len(frame)}), flush=True)
            for config in configs:
                events: list[v1.Event] = []
                for (event_day, symbol), frame in frames.items():
                    events.extend(v2.signal_events_v2(frame, config, event_day, symbol))
                event_counts[config.config_id] += len(events)
                for fee in FEE_LEVELS:
                    key = (config.config_id, fee)
                    trades, state = v5.simulate_account_day_v5(
                        frames,
                        events,
                        config,
                        fee,
                        state_store[key],
                    )
                    trade_store[key].extend(trades)
                    state_store[key] = state
            print(json.dumps({
                "stage": "development_v5_day_complete",
                "day": day,
                "representatives": len(configs),
            }), flush=True)

    rows: list[dict] = []
    selections: list[dict] = []
    ledgers: list[pd.DataFrame] = []
    for config in configs:
        metrics_by_fee: dict[float, dict] = {}
        for fee in FEE_LEVELS:
            key = (config.config_id, fee)
            trades = trade_store[key]
            metrics = v5.account_metrics_v5(trades, state_store[key], DEVELOPMENT_DAYS)
            metrics_by_fee[fee] = metrics
            rows.append({
                "config_id": config.config_id,
                **asdict(config),
                "fee_bps_per_side": fee,
                "event_count": event_counts[config.config_id],
                **{name: value for name, value in metrics.items() if not isinstance(value, dict)},
            })
            if fee == 5.0 and trades:
                ledger = pd.DataFrame([asdict(item) for item in trades])
                ledger["config_id"] = config.config_id
                ledgers.append(ledger)
        selected = d2.passes(metrics_by_fee)
        selections.append({
            "config_id": config.config_id,
            "config": asdict(config),
            "development_pass": selected,
            "metrics": {str(fee): metrics_by_fee[fee] for fee in FEE_LEVELS},
        })
        print(json.dumps({
            "stage": "development_v5_gate",
            "config_id": config.config_id,
            "development_pass": selected,
        }), flush=True)

    pd.DataFrame(rows).to_csv(output / "DEVELOPMENT_GRID.csv", index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(output / "DEVELOPMENT_5BPS_LEDGERS.csv", index=False)
    passed = [item for item in selections if item["development_pass"]]
    passed.sort(
        key=lambda item: min(
            item["metrics"]["5.0"]["return_2022"],
            item["metrics"]["5.0"]["return_2023"],
            item["metrics"]["7.5"]["total_return"],
            item["metrics"]["10.0"]["total_return"],
        ),
        reverse=True,
    )
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-1850-XVENUE-001",
        "stage": "MICROSECOND_LOCAL_ARRIVAL_RISK_BASED_DEVELOPMENT_V5",
        "causal_version": v5.CAUSAL_VERSION,
        "account_engine_version": "5",
        "development_days": list(DEVELOPMENT_DAYS),
        "development_opened": True,
        "representatives_tested": len(configs),
        "development_gate_pass_count": len(passed),
        "family_selections": selections,
        "frozen_development_representatives": passed[:12],
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "ranking_eligible": False,
        "v1_v2_v3_v4_v4b_promotion_admissible": False,
        "availability_clock": "local_timestamp_microsecond",
        "execution_contract": "first adverse actual quote at aligned boundary; completed-bucket triggers; configured entry and exit latency",
        "source_records": source_records,
        "source_latency_diagnostics": v2.LATENCY_DIAGNOSTICS,
    }
    path = output / "DEVELOPMENT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (output / "DEVELOPMENT_RESULT.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
        encoding="utf-8",
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
        "causal_version": result["causal_version"],
        "development_gate_pass_count": int(result.get("development_gate_pass_count", 0)),
        "selection_opened": False,
        "2026_opened": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
