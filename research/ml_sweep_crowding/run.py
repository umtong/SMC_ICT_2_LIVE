#!/usr/bin/env python3
"""Execute the frozen ML sweep/crowding source-to-account decision."""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .account import (
    model_diagnostics, select_pre2024_configuration, simulate, summarize_trades
)
from .common import (
    UTC, CachedDownloader, EconomicGateError, MarketData, SimConfig, StageSpec,
    SourceGateError, load_contract, sha256_file, sha256_json, utc_timestamp
)
from .source_data import download_bybit_months, load_market
from .strategy import (
    build_candidates_for_symbol, build_global_sequence, fit_model, score_candidates,
    select_event_actions
)

CONTRACT_PATH = Path(__file__).with_name("contract.json")

def serialize(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {key: serialize(val) for key, val in dataclasses.asdict(value).items()}
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Series):
        return {str(key): serialize(val) for key, val in value.items()}
    if isinstance(value, pd.DataFrame):
        return [serialize(row) for row in value.to_dict(orient="records")]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float):
        return None if not np.isfinite(value) else value
    if isinstance(value, dict):
        return {str(key): serialize(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(item) for item in value]
    return value


def write_report(result: Mapping[str, Any], path: Path) -> None:
    status = result["status"]
    lines = [
        "# ML Sweep/Crowding State Transition Result",
        "",
        f"- Result ID: `{result['result_id']}`",
        f"- Claim: `{result['claim_id']}`",
        f"- Status: **{status}**",
        f"- Contract SHA-256: `{result['contract_sha256']}`",
        "- Live orders: none",
        "",
        "## Mechanism",
        "",
        "A completed external-liquidity sweep creates two mutually exclusive candidates: leveraged continuation through the level and absorption/reversal back through it. The fixed pooled HGBT uses completed Bybit price/volume state and one-observation-delayed Binance USD-M positioning/flow to choose one action or abstain.",
        "",
        "## Pre-2024 decision",
        "",
    ]
    pre = result.get("pre2024")
    if pre:
        lines.extend(
            [
                f"- Selected threshold: `{pre['config']['threshold']}`",
                f"- Risk fraction: `{pre['config']['risk_fraction']}`",
                f"- Leverage constraint: `{pre['config']['leverage']}`",
                f"- Final NAV: `{pre['final_nav']:.6f}` USDT",
                f"- Geometric daily growth: `{100 * pre['geometric_daily_growth']:.8f}%`",
                f"- MDD: `{100 * pre['max_drawdown']:.4f}%`",
                f"- Completed trades: `{pre['trade_summary']['completed_trades']}`",
                "",
            ]
        )
    else:
        error = result.get("error", "No pre-2024 account result opened.")
        lines.extend([f"No pre-2024 account result opened: `{error}`", ""])
    official = result.get("official_2024h1")
    if official:
        lines.extend(
            [
                "## Official 2024H1",
                "",
                f"- Final NAV: `{official['final_nav']:.6f}` USDT",
                f"- Total return: `{100 * (official['final_nav'] / 10000 - 1):.6f}%`",
                f"- Geometric daily growth: `{100 * official['geometric_daily_growth']:.8f}%`",
                f"- MDD: `{100 * official['max_drawdown']:.4f}%`",
                f"- Completed trades: `{official['trade_summary']['completed_trades']}`",
                f"- Profit factor: `{official['trade_summary']['profit_factor']}`",
                f"- Median trade/NAV: `{100 * official['trade_summary']['median_trade_return_on_nav']:.6f}%`",
                f"- Top-five positive-PnL share: `{official['trade_summary']['positive_pnl_top5_share']}`",
                f"- Winner-removal final NAV: `{official['winner_removal']['final_nav']:.6f}`",
                f"- Winner-removal geometric daily growth: `{100 * official['winner_removal']['geometric_daily_growth']:.8f}%`",
                "",
                "### Cost stress",
                "",
            ]
        )
        for stress in official["cost_stress"]:
            lines.append(
                f"- `{stress['round_trip_bps']}bp`: NAV `{stress['final_nav']:.6f}`, daily growth `{100 * stress['geometric_daily_growth']:.8f}%`, valid `{stress['valid']}`"
            )
        lines.append("")
    lines.extend(
        [
            "## Causality and execution",
            "",
            "- Every signal uses a completed five-minute bar.",
            "- Binance metrics are delayed by one complete observation.",
            "- The fixed 500ms latency enters no earlier than the next observable one-minute open.",
            "- Stop/target ambiguity is adverse-first; gap-through stops use the adverse open.",
            "- Actual Bybit funding settlements are applied to signed notional.",
            "- There is no time-based strategy exit; interval boundaries NAV-mark open exposure.",
            "- One global slot is enforced across BTCUSDT and ETHUSDT.",
            "",
            "## Decision",
            "",
            result["decision"],
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run(contract: Mapping[str, Any], cache_dir: Path, output_dir: Path) -> dict[str, Any]:
    start = utc_timestamp(contract["data"]["bybit_1m_start"])
    end_exclusive = utc_timestamp("2024-07-01T00:00:00Z")
    symbols = list(contract["symbols"])
    downloader = CachedDownloader(cache_dir)
    bybit_paths = download_bybit_months(downloader, symbols, start, end_exclusive)
    markets: dict[str, MarketData] = {}
    for symbol in symbols:
        print(f"[source] loading {symbol}", flush=True)
        markets[symbol] = load_market(
            symbol, bybit_paths[symbol], downloader, contract, start, end_exclusive
        )
    candidate_parts = []
    for symbol in symbols:
        print(f"[events] constructing {symbol}", flush=True)
        candidate_parts.append(build_candidates_for_symbol(markets[symbol], contract))
    candidates = pd.concat(candidate_parts, ignore_index=True)
    candidates = candidates.sort_values(["entry_ts", "symbol", "event_id", "is_continuation"])

    train_end = utc_timestamp(contract["model"]["base_train_end_exclusive"])
    train_start = utc_timestamp(contract["model"]["base_train_start"])
    resolved_train = candidates.loc[
        (candidates["signal_ts"] >= train_start)
        & (candidates["signal_ts"] < train_end)
        & (candidates["resolution"].isin(["target", "stop"]))
        & (candidates["exit_ts_full"] < train_end)
        & (~candidates["path_invalid"])
    ].copy()
    base_model = fit_model(resolved_train, contract)
    scored_all = score_candidates(base_model, candidates)

    selection = StageSpec(
        "calendar_2023",
        utc_timestamp(contract["model"]["selection_start"]),
        utc_timestamp(contract["model"]["selection_end_exclusive"]),
        365,
    )
    config, sequence_2023, pre_result, grid = select_pre2024_configuration(
        scored_all, markets, selection, contract
    )
    source_manifest = {
        symbol: {
            "one_minute_coverage": markets[symbol].coverage,
            "one_minute_manifest_sha256": markets[symbol].one_minute_sha256,
            "metrics_sha256": markets[symbol].metrics_sha256,
            "funding_sha256": markets[symbol].funding_sha256,
            "one_minute_rows": int(markets[symbol].one_minute["close"].notna().sum()),
            "five_minute_rows": int(len(markets[symbol].five_minute)),
            "funding_rows": int(len(markets[symbol].funding)),
        }
        for symbol in symbols
    }
    result: dict[str, Any] = {
        "schema_version": 1,
        "result_id": "RES-20260727-ML-SWEEP-CROWDING-001",
        "claim_id": contract["claim_id"],
        "status": "PRE2024_CLOSED",
        "contract_sha256": sha256_file(CONTRACT_PATH),
        "source_manifest": source_manifest,
        "source_manifest_sha256": sha256_json(source_manifest),
        "candidate_rows": int(len(candidates)),
        "base_model": model_diagnostics(base_model, resolved_train),
        "pre2024": {
            "config": dataclasses.asdict(config),
            "final_nav": pre_result.final_nav,
            "geometric_daily_growth": pre_result.geometric_daily_growth,
            "max_drawdown": pre_result.max_drawdown,
            "valid": pre_result.valid,
            "trade_summary": summarize_trades(pre_result),
        },
        "grid_cells": int(len(grid)),
        "orders_submitted": False,
        "paper_live_started": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(grid).to_csv(output_dir / "pre2024_grid.csv", index=False)
    pre_result.trades.to_csv(output_dir / "pre2024_selected_trades.csv", index=False)

    if not pre_result.valid or pre_result.final_nav <= float(contract["sizing"]["start_nav_usdt"]):
        result["decision"] = (
            "The frozen calendar-2023 account did not produce positive after-cost NAV. "
            "The exact sweep/crowding route is retired without adjacent threshold, feature, stop, risk or leverage rescue."
        )
        return result

    official_start = utc_timestamp(contract["model"]["official_h1_start"])
    resolved_pre2024 = candidates.loc[
        (candidates["signal_ts"] >= train_start)
        & (candidates["signal_ts"] < official_start)
        & (candidates["resolution"].isin(["target", "stop"]))
        & (candidates["exit_ts_full"] < official_start)
        & (~candidates["path_invalid"])
    ].copy()
    official_model = fit_model(resolved_pre2024, contract)
    scored_official = score_candidates(official_model, candidates)
    official = StageSpec(
        "official_2024h1",
        official_start,
        utc_timestamp(contract["model"]["official_h1_end_exclusive"]),
        182,
    )
    activation = official.start + pd.Timedelta(
        minutes=int(contract["model"]["semiannual_activation_delay_minutes"])
    )
    pre_activation = scored_all.loc[scored_all["entry_ts"] < activation]
    post_activation = scored_official.loc[scored_official["entry_ts"] >= activation]
    official_scores = pd.concat([pre_activation, post_activation], ignore_index=True)
    selected_h1 = select_event_actions(official_scores, config.threshold, official)
    sequence_h1 = build_global_sequence(selected_h1, official)
    official_config = SimConfig(
        config.threshold,
        config.risk_fraction,
        config.leverage,
        float(contract["execution"]["base_round_trip_bps"]),
    )
    official_result = simulate(sequence_h1, markets, official, official_config, contract)
    if not official_result.valid:
        result["status"] = "OFFICIAL_2024H1_INVALID_ACCOUNT"
        result["decision"] = f"Official 2024H1 account invalid: {official_result.invalid_reason}"
        return result
    completed = official_result.trades.loc[~official_result.trades["stage_mark"]]
    positive_ids = set(
        completed.loc[completed.pnl > 0].nlargest(5, "pnl")["sequence_id"].astype(int).tolist()
    )
    winner_removed = simulate(
        sequence_h1, markets, official, official_config, contract, skip_sequence_ids=positive_ids
    )
    stresses = []
    for bps in contract["execution"]["stress_round_trip_bps"]:
        stress_config = SimConfig(config.threshold, config.risk_fraction, config.leverage, float(bps))
        stress = simulate(sequence_h1, markets, official, stress_config, contract)
        stresses.append(
            {
                "round_trip_bps": float(bps),
                "valid": stress.valid,
                "final_nav": stress.final_nav,
                "geometric_daily_growth": stress.geometric_daily_growth,
                "max_drawdown": stress.max_drawdown,
            }
        )
    official_result.trades.to_csv(output_dir / "official_2024h1_trades.csv", index=False)
    official_result.daily_nav.rename("nav").to_csv(output_dir / "official_2024h1_daily_nav.csv")
    result["status"] = "OFFICIAL_2024H1_COMPLETE"
    result["official_model"] = model_diagnostics(official_model, resolved_pre2024)
    result["official_2024h1"] = {
        "config": dataclasses.asdict(official_config),
        "final_nav": official_result.final_nav,
        "geometric_daily_growth": official_result.geometric_daily_growth,
        "max_drawdown": official_result.max_drawdown,
        "valid": official_result.valid,
        "trade_summary": summarize_trades(official_result),
        "winner_removal": {
            "removed_sequence_ids": sorted(positive_ids),
            "final_nav": winner_removed.final_nav,
            "geometric_daily_growth": winner_removed.geometric_daily_growth,
            "max_drawdown": winner_removed.max_drawdown,
            "valid": winner_removed.valid,
        },
        "cost_stress": stresses,
        "current_first_place_geometric_daily_growth": 0.000387317,
        "beats_current_first_place": official_result.geometric_daily_growth > 0.000387317,
        "target_gap": 0.01 - official_result.geometric_daily_growth,
    }
    if official_result.geometric_daily_growth > 0.000387317:
        result["decision"] = (
            "The hard-valid official 2024H1 account beats the recorded first place and must be inserted into the cumulative ranking."
        )
    else:
        result["decision"] = (
            "The route survived pre-2024 but official 2024H1 did not beat the recorded first place. "
            "It is recorded at its measured rank and is not rescued by adjacent tuning."
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    global CONTRACT_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/ml_sweep_crowding"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("research/results/ml_sweep_crowding")
    )
    args = parser.parse_args(argv)
    CONTRACT_PATH = args.contract
    contract = load_contract(args.contract)
    started = pd.Timestamp.now(tz=UTC)
    try:
        result = run(contract, args.cache_dir, args.output_dir)
    except SourceGateError as exc:
        result = {
            "schema_version": 1,
            "result_id": "RES-20260727-ML-SWEEP-CROWDING-001",
            "claim_id": contract["claim_id"],
            "status": "SOURCE_GATE_FAIL",
            "contract_sha256": sha256_file(args.contract),
            "error": str(exc),
            "decision": "The frozen source/schema/coverage gate failed before an economic result opened. The exact route is closed without outcome inference.",
            "orders_submitted": False,
            "paper_live_started": False,
        }
    except EconomicGateError as exc:
        result = {
            "schema_version": 1,
            "result_id": "RES-20260727-ML-SWEEP-CROWDING-001",
            "claim_id": contract["claim_id"],
            "status": "ECONOMIC_PIPELINE_FAIL",
            "contract_sha256": sha256_file(args.contract),
            "error": str(exc),
            "decision": "The frozen economic pipeline could not form a decision-ready account. The exact route is closed without adjacent rescue.",
            "orders_submitted": False,
            "paper_live_started": False,
        }
    finished = pd.Timestamp.now(tz=UTC)
    result["started_at"] = started.isoformat()
    result["finished_at"] = finished.isoformat()
    result["runtime_seconds"] = float((finished - started).total_seconds())
    result = serialize(result)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_report(result, args.output_dir / "report.md")
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
