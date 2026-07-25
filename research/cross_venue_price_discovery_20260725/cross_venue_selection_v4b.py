from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import cross_venue_pilot as v1
import cross_venue_pilot_v2 as v2
import cross_venue_development_v2 as d2
import cross_venue_development_v3 as d3
import cross_venue_development_v4b as d4b

SELECTION_DAYS = tuple(f"2024-{month:02d}-01" for month in range(1, 13))
FEE_LEVELS = d2.FEE_LEVELS


def config_from_frozen(item: dict) -> v1.Config:
    return v1.Config(**item["config"])


def removed_path_return(frame: pd.DataFrame, fraction: float) -> float | None:
    if frame.empty:
        return None
    count = max(1, int(math.ceil(len(frame) * fraction)))
    removed = set(frame.nlargest(count, "account_return").index)
    retained = frame.loc[~frame.index.isin(removed), "account_return"].to_numpy(float)
    return float(np.prod(1.0 + retained) - 1.0) if len(retained) else None


def metrics_for_days(trades: list[d3.AccountTradeV3], state: dict[str, float], days: tuple[str, ...]) -> dict:
    if not trades:
        return {
            "n": 0,
            "eligible_days": len(days),
            "trades_per_day_median": 0.0,
            "positive_day_fraction": 0.0,
            "total_return": 0.0,
            "geometric_sample_day_return": 0.0,
            "profit_factor": None,
            "maximum_drawdown": 0.0,
            "closed_path_drawdown": 0.0,
            "maximum_intratrade_drawdown": 0.0,
            "top10pct_removed_return": None,
            "top5_positive_share": 1.0,
            "maximum_single_symbol_positive_pnl_share": 1.0,
        }
    frame = pd.DataFrame([asdict(item) for item in trades])
    daily = frame.groupby("day").account_return.apply(
        lambda values: float(np.prod(1.0 + values.to_numpy(float)) - 1.0)
    ).reindex(days, fill_value=0.0)
    positive_frame = frame.loc[frame.net_pnl > 0].copy()
    positive = positive_frame.net_pnl.to_numpy(float)
    negative = frame.loc[frame.net_pnl < 0, "net_pnl"].to_numpy(float)
    positive_sum = float(positive.sum())
    positive_by_symbol = positive_frame.groupby("symbol").net_pnl.sum()
    counts = frame.groupby("day").size().reindex(days, fill_value=0)
    nav = np.r_[d2.INITIAL_NAV, frame.nav_after.to_numpy(float)]
    peak = np.maximum.accumulate(nav)
    closed_drawdown = float(np.max(1.0 - nav / np.maximum(peak, 1e-12)))
    intratrade = float(frame.maximum_intratrade_drawdown.max())
    combined = min(1.0, closed_drawdown + intratrade)
    return {
        "n": int(len(frame)),
        "eligible_days": len(days),
        "trades_per_day_median": float(counts.median()),
        "positive_day_fraction": float((daily > 0).mean()),
        "total_return": float(state["ending_nav"] / d2.INITIAL_NAV - 1.0),
        "geometric_sample_day_return": float(np.expm1(np.log1p(daily).mean())),
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) else None,
        "maximum_drawdown": max(float(state["maximum_drawdown"]), combined),
        "closed_path_drawdown": closed_drawdown,
        "maximum_intratrade_drawdown": intratrade,
        "top10pct_removed_return": removed_path_return(frame, 0.10),
        "top5_positive_share": float(np.sort(positive)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0,
        "maximum_single_symbol_positive_pnl_share": float(positive_by_symbol.max() / positive_sum) if positive_sum > 0 else 1.0,
        "symbol_net_pnl": frame.groupby("symbol").net_pnl.sum().to_dict(),
        "symbol_positive_pnl": positive_by_symbol.to_dict(),
        "day_returns": daily.to_dict(),
        "exit_liquidity_overrun_count": int(frame.exit_liquidity_overrun.sum()),
    }


def selection_pass(metrics_by_fee: dict[float, dict]) -> bool:
    base = metrics_by_fee[5.0]
    return (
        base["n"] >= 200
        and all(metrics_by_fee[fee]["total_return"] > 0 for fee in FEE_LEVELS)
        and base["positive_day_fraction"] >= 0.58
        and (base["top10pct_removed_return"] is not None and base["top10pct_removed_return"] > 0)
        and (base["profit_factor"] is not None and base["profit_factor"] >= 1.05)
        and base["maximum_drawdown"] <= 0.20
        and base["maximum_single_symbol_positive_pnl_share"] <= 0.70
    )


def run(predecessor: Path, output: Path, cache: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    d4b.patch_once()
    predecessor_result = predecessor / "DEVELOPMENT_RESULT.json"
    if not predecessor_result.exists():
        raise FileNotFoundError("predecessor DEVELOPMENT_RESULT.json missing")
    raw = predecessor_result.read_bytes()
    development = json.loads(raw)
    if development.get("account_engine_version") != "4B":
        raise ValueError("predecessor is not authoritative V4B")
    if development.get("selection_opened") is not False or development.get("2026_opened") is not False:
        raise ValueError("predecessor sealing flags invalid")
    frozen = development.get("frozen_development_representatives", [])
    if int(development.get("development_gate_pass_count", 0)) <= 0 or not frozen:
        result = {
            "schema_version": 1,
            "claim_id": "CLM-20260725-1850-XVENUE-001",
            "stage": "SELECTION_BLOCKED_BY_DEVELOPMENT_GATE",
            "predecessor_sha256": hashlib.sha256(raw).hexdigest(),
            "selection_opened": False,
            "confirmation_opened": False,
            "2026_opened": False,
            "orders_submitted": False,
            "paper_live_started": False,
            "champion_eligible": False,
        }
        path = output / "SELECTION_RESULT.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result

    configs = [config_from_frozen(item) for item in frozen[:12]]
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    sources: list[dict] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-venue-selection-v4b/1.0"
        for day in SELECTION_DAYS:
            for symbol in v1.SYMBOLS:
                frame, records = v1.load_day(cache, session, day, symbol)
                frames[(day, symbol)] = frame
                sources.extend(records)
                print(json.dumps({"day": day, "symbol": symbol, "aligned_rows": len(frame)}), flush=True)

    selections = []
    rows = []
    ledgers = []
    for config in configs:
        events: list[v1.Event] = []
        for (day, symbol), frame in frames.items():
            events.extend(v2.signal_events_v2(frame, config, day, symbol))
        by_fee = {}
        for fee in FEE_LEVELS:
            trades, state = d2.simulate_account(frames, events, config, fee)
            metrics = metrics_for_days(trades, state, SELECTION_DAYS)
            by_fee[fee] = metrics
            rows.append({
                "config_id": config.config_id,
                **asdict(config),
                "fee_bps_per_side": fee,
                "event_count": len(events),
                **{key: value for key, value in metrics.items() if not isinstance(value, dict)},
            })
            if fee == 5.0 and trades:
                ledger = pd.DataFrame([asdict(item) for item in trades])
                ledger["config_id"] = config.config_id
                ledgers.append(ledger)
        passed = selection_pass(by_fee)
        selections.append({
            "config_id": config.config_id,
            "config": asdict(config),
            "selection_pass": passed,
            "metrics": {str(fee): by_fee[fee] for fee in FEE_LEVELS},
        })
        print(json.dumps({"config_id": config.config_id, "selection_pass": passed}), flush=True)

    pd.DataFrame(rows).to_csv(output / "SELECTION_GRID.csv", index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(output / "SELECTION_5BPS_LEDGERS.csv", index=False)
    passed = [item for item in selections if item["selection_pass"]]
    passed.sort(
        key=lambda item: min(
            item["metrics"]["5.0"]["total_return"],
            item["metrics"]["7.5"]["total_return"],
            item["metrics"]["10.0"]["total_return"],
            item["metrics"]["5.0"]["top10pct_removed_return"],
        ),
        reverse=True,
    )
    primary = passed[0] if passed else None
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-1850-XVENUE-001",
        "stage": "FROZEN_2024_SELECTION",
        "predecessor_sha256": hashlib.sha256(raw).hexdigest(),
        "account_engine_version": "4B",
        "selection_days": list(SELECTION_DAYS),
        "selection_opened": True,
        "candidates_tested": len(configs),
        "selection_gate_pass_count": len(passed),
        "family_selections": selections,
        "frozen_primary": primary,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
        "paper_live_started": False,
        "champion_eligible": False,
        "source_records": sources,
    }
    path = output / "SELECTION_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (output / "SELECTION_RESULT.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8"
    )
    if primary:
        primary_path = output / "FROZEN_PRIMARY.json"
        primary_path.write_text(json.dumps(primary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.predecessor, args.output, args.cache)
    print(json.dumps({
        "stage": result["stage"],
        "selection_opened": result["selection_opened"],
        "selection_gate_pass_count": int(result.get("selection_gate_pass_count", 0)),
        "confirmation_opened": False,
        "2026_opened": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
