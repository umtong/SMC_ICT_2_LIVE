from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import cross_venue_execution_v5 as v5
import cross_venue_execution_v5d as v5d
import cross_venue_pilot as v1
import cross_venue_pilot_v5 as pilot_v5
import cross_venue_pilot_v5c as v5c

FEE_LEVELS = pilot_v5.FEE_LEVELS


def _as_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes"}


def _trade_from_row(row: pd.Series) -> v5.FixedTradeV5:
    gross = float(row["gross_bps"])
    return v5.FixedTradeV5(
        config_id=str(row["config_id"]),
        day=str(row["day"]),
        symbol=str(row["symbol"]),
        family=str(row["family"]),
        decision_ms=int(row["decision_ms"]),
        entry_ms=int(row["entry_ms"]),
        exit_ms=int(row["exit_ms"]),
        entry_us=int(row["entry_us"]),
        exit_us=int(row["exit_us"]),
        side=int(row["side"]),
        entry_price=float(row["entry_price"]),
        exit_price=float(row["exit_price"]),
        gross_bps=gross,
        spread_bps=float(row["spread_bps"]),
        fee_bps_per_side=0.0,
        net_bps=gross,
        exit_reason=str(row["exit_reason"]),
        score=float(row["score"]),
        exit_liquidity_overrun=_as_bool(row["exit_liquidity_overrun"]),
        trigger_boundary_us=int(row["trigger_boundary_us"]),
    )


def _find_shards(input_root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for result_path in sorted(input_root.rglob("PILOT_RESULT.json")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        days = result.get("pilot_days")
        if not isinstance(days, list) or len(days) != 1:
            continue
        day = str(days[0])
        if day not in v1.PILOT_DAYS:
            continue
        if day in found:
            raise ValueError(f"duplicate pilot shard for {day}: {found[day]} and {result_path.parent}")
        found[day] = result_path.parent
    missing = [day for day in v1.PILOT_DAYS if day not in found]
    if missing:
        raise ValueError(f"missing frozen pilot shards: {missing}")
    return found


def _validate_shard(
    day: str,
    directory: Path,
    config_ids: set[str],
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    result = json.loads((directory / "PILOT_RESULT.json").read_text(encoding="utf-8"))
    if result.get("causal_version") != v5d.CAUSAL_VERSION:
        raise ValueError(f"{day} causal version mismatch")
    if result.get("causal_engine_version") != v5d.ENGINE_VERSION:
        raise ValueError(f"{day} engine version mismatch")
    if result.get("pilot_days") != [day]:
        raise ValueError(f"{day} shard date mismatch")
    if result.get("configurations") != len(config_ids):
        raise ValueError(f"{day} configuration count mismatch")
    if result.get("v1_v2_v3_v4_v4b_v5_v5b_v5c_outputs_admissible") is not False:
        raise ValueError(f"{day} did not reject superseded engines")
    if result.get("orders_submitted") is not False:
        raise ValueError(f"{day} order boundary violated")

    grid = pd.read_csv(directory / "PILOT_GRID.csv")
    grid["config_id"] = grid["config_id"].astype(str)
    if set(grid["config_id"]) != config_ids:
        raise ValueError(f"{day} grid configuration identities mismatch")
    counts = grid.groupby("config_id").size()
    if not (counts == len(FEE_LEVELS)).all():
        raise ValueError(f"{day} grid does not contain every frozen fee replay")

    ledger_path = directory / "PILOT_5BPS_LEDGERS.csv"
    ledger = pd.read_csv(ledger_path) if ledger_path.exists() else pd.DataFrame()
    if not ledger.empty:
        ledger["config_id"] = ledger["config_id"].astype(str)
        ledger["day"] = ledger["day"].astype(str)
        if set(ledger["day"]) != {day}:
            raise ValueError(f"{day} ledger contains another date")
        unknown = set(ledger["config_id"]).difference(config_ids)
        if unknown:
            raise ValueError(f"{day} ledger contains unknown configurations: {sorted(unknown)[:3]}")
    return result, grid, ledger


def run(input_root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    configs = v1.pilot_grid()
    config_ids = {config.config_id for config in configs}
    if len(config_ids) != len(configs):
        raise AssertionError("frozen V5D pilot grid contains duplicate configuration IDs")

    shards = _find_shards(input_root)
    day_results: list[dict] = []
    day_ledgers: list[pd.DataFrame] = []
    event_counts = {config.config_id: 0 for config in configs}

    for day in v1.PILOT_DAYS:
        result, grid, ledger = _validate_shard(day, shards[day], config_ids)
        day_results.append(result)
        if not ledger.empty:
            day_ledgers.append(ledger)
        one = grid[["config_id", "event_count"]].drop_duplicates("config_id")
        if len(one) != len(configs):
            raise ValueError(f"{day} event-count rows are incomplete")
        for row in one.itertuples(index=False):
            event_counts[str(row.config_id)] += int(row.event_count)

    combined_ledger = pd.concat(day_ledgers, ignore_index=True) if day_ledgers else pd.DataFrame()
    if not combined_ledger.empty:
        day_order = {day: index for index, day in enumerate(v1.PILOT_DAYS)}
        combined_ledger["_day_order"] = combined_ledger["day"].astype(str).map(day_order)
        if combined_ledger["_day_order"].isna().any():
            raise ValueError("combined ledger contains a non-preregistered date")
        combined_ledger = combined_ledger.sort_values(
            ["config_id", "_day_order", "entry_us", "score", "symbol"],
            ascending=[True, True, True, False, True],
        ).drop(columns="_day_order").reset_index(drop=True)
        combined_ledger.to_csv(output / "PILOT_5BPS_LEDGERS.csv", index=False)

    by_config: dict[str, list[v5.FixedTradeV5]] = {config.config_id: [] for config in configs}
    if not combined_ledger.empty:
        for _, row in combined_ledger.iterrows():
            trade = _trade_from_row(row)
            by_config[trade.config_id].append(trade)

    v5c.patch_metrics(tuple(v1.PILOT_DAYS))
    rows: list[dict] = []
    for config in configs:
        gross_trades = by_config[config.config_id]
        for fee in FEE_LEVELS:
            trades = v5.apply_fixed_fee(gross_trades, fee)
            summary = v1.metrics(trades)
            rows.append({
                "config_id": config.config_id,
                **asdict(config),
                "fee_bps_per_side": fee,
                "event_count": event_counts[config.config_id],
                **{key: value for key, value in summary.items() if not isinstance(value, dict)},
            })

    grid = pd.DataFrame(rows)
    grid.to_csv(output / "PILOT_GRID.csv", index=False)
    base = grid.loc[grid.fee_bps_per_side == 5.0].copy()
    zero = grid.loc[
        grid.fee_bps_per_side == 0.0,
        ["config_id", "mean_net_bps", "total_fixed_notional_return"],
    ].rename(columns={
        "mean_net_bps": "zero_fee_mean_bps",
        "total_fixed_notional_return": "zero_fee_total_return",
    })
    stress = grid.loc[
        grid.fee_bps_per_side == 10.0,
        ["config_id", "mean_net_bps", "total_fixed_notional_return"],
    ].rename(columns={
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

    template = dict(day_results[0])
    template.update({
        "stage": "MICROSECOND_LOCAL_ARRIVAL_FATAL_EDGE_PILOT_V5D_DATE_PARALLEL",
        "pilot_days": list(v1.PILOT_DAYS),
        "configurations": len(configs),
        "fatal_edge_pass_count": int(candidates.fatal_edge_pass.sum()),
        "best": candidates.iloc[0].replace({np.nan: None}).to_dict() if len(candidates) else None,
        "full_development_opened": False,
        "development_opened": False,
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "ranking_eligible": False,
        "pilot_day_denominator": "all preregistered pilot dates including zero-trade dates",
        "performance_contract": (
            "four disjoint frozen dates are replayed independently in parallel; their exact V5D gross ledgers "
            "are concatenated chronologically and all fee and fatal-gate metrics are recomputed once"
        ),
        "parallelization_contract": {
            "shards": list(v1.PILOT_DAYS),
            "scientific_dependencies_changed": False,
            "cross_day_slot_overlap_possible": False,
            "fee_replay_recomputed_after_merge": True,
        },
        "source_records": [record for result in day_results for record in result.get("source_records", [])],
        "source_latency_diagnostics": [
            record
            for result in day_results
            for record in result.get("source_latency_diagnostics", [])
        ],
    })
    result_path = output / "PILOT_RESULT.json"
    result_path.write_text(
        json.dumps(template, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (output / "PILOT_RESULT.sha256").write_text(
        f"{hashlib.sha256(result_path.read_bytes()).hexdigest()}  {result_path.name}\n",
        encoding="utf-8",
    )
    equivalence = {
        "schema_version": 1,
        "claim_id": template["claim_id"],
        "engine": template["causal_engine_version"],
        "parallel_unit": "disjoint UTC sample day",
        "configuration_ids_sha256": hashlib.sha256(
            "\n".join(config.config_id for config in configs).encode()
        ).hexdigest(),
        "combined_ledger_sha256": (
            hashlib.sha256((output / "PILOT_5BPS_LEDGERS.csv").read_bytes()).hexdigest()
            if (output / "PILOT_5BPS_LEDGERS.csv").exists()
            else hashlib.sha256(b"").hexdigest()
        ),
        "scientific_dependencies_changed": False,
        "orders_submitted": False,
    }
    (output / "PARALLEL_EQUIVALENCE.json").write_text(
        json.dumps(equivalence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "fatal_edge_pass_count": template["fatal_edge_pass_count"],
        "configuration_count": len(configs),
        "ledger_rows": int(len(combined_ledger)),
        "pilot_days": list(v1.PILOT_DAYS),
    }, indent=2, sort_keys=True))
    return template


def self_test() -> None:
    configs = v1.pilot_grid()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        parts = root / "parts"
        output = root / "aggregate"
        for day in v1.PILOT_DAYS:
            directory = parts / day
            directory.mkdir(parents=True)
            result = {
                "schema_version": 1,
                "claim_id": "CLM-20260725-1850-XVENUE-001",
                "causal_version": v5d.CAUSAL_VERSION,
                "causal_engine_version": v5d.ENGINE_VERSION,
                "pilot_days": [day],
                "configurations": len(configs),
                "v1_v2_v3_v4_v4b_v5_v5b_v5c_outputs_admissible": False,
                "funding_boundary_contract": "frozen",
                "protective_stop_contract": "frozen",
                "source_continuity_contract": "frozen",
                "execution_gap_contract": "frozen",
                "exit_floor_contract": "frozen",
                "drawdown_contract": "frozen",
                "orders_submitted": False,
                "source_records": [],
                "source_latency_diagnostics": [],
            }
            (directory / "PILOT_RESULT.json").write_text(
                json.dumps(result, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            rows = [
                {
                    "config_id": config.config_id,
                    "fee_bps_per_side": fee,
                    "event_count": 1,
                }
                for config in configs
                for fee in FEE_LEVELS
            ]
            pd.DataFrame(rows).to_csv(directory / "PILOT_GRID.csv", index=False)
        result = run(parts, output)
        grid = pd.read_csv(output / "PILOT_GRID.csv")
        assert result["fatal_edge_pass_count"] == 0
        assert result["pilot_days"] == list(v1.PILOT_DAYS)
        assert len(grid) == len(configs) * len(FEE_LEVELS)
        assert set(grid.event_count.astype(int)) == {len(v1.PILOT_DAYS)}
        assert not (output / "PILOT_5BPS_LEDGERS.csv").exists()
        print("V5D_DATE_PARALLEL_AGGREGATION_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--input-root", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        run(args.input_root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
