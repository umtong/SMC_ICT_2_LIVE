#!/usr/bin/env python3
"""Frozen 2024-H1 replay of 2023-selected YT Trinity structural alpha gates.

The alpha gates, gate priority, portfolios, risk fractions, and stress grid are
selected entirely from 2023 data. This runner never fits or selects on 2024-H1.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import json
from math import exp, log
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from run_research import PRIMARY, load_canonical_frames
from system.coarse import CoarseEventReplay, CoarseExecutionConfig, coarse_closeout_price
from system.core import EventFamily, FeatureConfig, RiskConfig
from system.corpus_alpha import build_corpus_features, generate_corpus_candidates_with_diagnostics
from system.metrics import summarize_account
from system.model import ScoredCandidate
from system.policy import GlobalSlotPolicy


GATE_PRIORITY = {
    "G1_BTC_CONT_EXTERNAL_EXPANSION": 0.84,
    "G3_REVERSAL_DEEP_SWEEP": 0.54,
    "G2_ETH_DEEP_RECLAIM": 0.53,
    "G4_CONT_DEEP_RECLAIM": 0.51,
}

# All variants were fixed using 2023 only. PRIMARY is the 2023 full-year
# growth winner; the rest are pre-registered sensitivity paths, not H1 choices.
CONFIGURATIONS = (
    {"id": "PRIMARY_P123_R30_L100", "gates": ("G1", "G2", "G3"), "risk": 0.30, "leverage": 100.0, "primary": True},
    {"id": "P123_R19_L100", "gates": ("G1", "G2", "G3"), "risk": 0.19, "leverage": 100.0, "primary": False},
    {"id": "P123_R10_L100", "gates": ("G1", "G2", "G3"), "risk": 0.10, "leverage": 100.0, "primary": False},
    {"id": "P1234_R19_L100", "gates": ("G1", "G2", "G3", "G4"), "risk": 0.19, "leverage": 100.0, "primary": False},
    {"id": "P23_R29_L100", "gates": ("G2", "G3"), "risk": 0.29, "leverage": 100.0, "primary": False},
    {"id": "P14_R16_L100", "gates": ("G1", "G4"), "risk": 0.16, "leverage": 100.0, "primary": False},
)
STRESS_ROUND_TRIP_BPS = (0.0, 6.0, 12.0, 24.0)


def f(candidate: Any, name: str, default: float = np.nan) -> float:
    value = candidate.feature_row.get(name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def matching_gates(candidate: Any) -> list[tuple[str, str, float]]:
    rows: list[tuple[str, str, float]] = []
    continuation = candidate.family == EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION
    reversal = candidate.family == EventFamily.LIQUIDITY_SWEEP_REVERSAL
    if (
        candidate.symbol == "BTCUSDT"
        and continuation
        and f(candidate, "target_distance_atr", -np.inf) >= 10.50
        and f(candidate, "bollinger_bandwidth", -np.inf) >= 0.00470
        and f(candidate, "draw_target_quality", -np.inf) >= 7.0
    ):
        rows.append(("G1", "MARKETABLE", GATE_PRIORITY["G1_BTC_CONT_EXTERNAL_EXPANSION"]))
    if (
        candidate.symbol == "ETHUSDT"
        and f(candidate, "stop_distance_atr", -np.inf) >= 4.55
        and f(candidate, "retest_depth_fraction", -np.inf) >= 1.99
        and f(candidate, "confirmation_age_bars", -np.inf) >= 7.0
    ):
        rows.append(("G2", "PASSIVE_RETEST", GATE_PRIORITY["G2_ETH_DEEP_RECLAIM"]))
    if (
        reversal
        and f(candidate, "sweep_depth_atr", -np.inf) >= 1.50
        and f(candidate, "target_distance_atr", -np.inf) >= 6.28
    ):
        rows.append(("G3", "MARKETABLE", GATE_PRIORITY["G3_REVERSAL_DEEP_SWEEP"]))
    if (
        continuation
        and f(candidate, "stop_distance_atr", -np.inf) >= 3.75
        and f(candidate, "retest_depth_fraction", -np.inf) >= 3.48
        and f(candidate, "path_excursion_atr", -np.inf) >= 4.17
    ):
        rows.append(("G4", "MARKETABLE", GATE_PRIORITY["G4_CONT_DEEP_RECLAIM"]))
    return sorted(rows, key=lambda row: row[2], reverse=True)


def score_for_portfolio(candidates: Iterable[Any], allowed: set[str]) -> tuple[list[ScoredCandidate], list[dict[str, Any]]]:
    scored: list[ScoredCandidate] = []
    ledger: list[dict[str, Any]] = []
    for candidate in candidates:
        eligible = [row for row in matching_gates(candidate) if row[0] in allowed]
        if not eligible:
            continue
        gate, action, priority = eligible[0]
        market_score = priority if action == "MARKETABLE" else -1.0
        passive_score = priority if action == "PASSIVE_RETEST" else -1.0
        scored.append(
            ScoredCandidate(
                candidate=candidate,
                win_probability=0.5,
                expected_net_r=priority,
                passive_fill_probability=1.0 if action == "PASSIVE_RETEST" else 0.0,
                expected_log_growth=priority,
                lower_confidence_score=priority,
                market_expected_log_growth=market_score,
                passive_expected_log_growth=passive_score,
                market_lower_confidence_score=market_score,
                passive_lower_confidence_score=passive_score,
                preferred_action=action,
            )
        )
        ledger.append(
            {
                "timestamp": candidate.timestamp,
                "symbol": candidate.symbol,
                "family": candidate.family.value,
                "side": candidate.side,
                "gate": gate,
                "action": action,
                "priority": priority,
                "entry_reference": candidate.entry_reference,
                "stop_reference": candidate.stop_reference,
                "target_reference": candidate.target_reference,
            }
        )
    scored.sort(key=lambda row: (row.candidate.timestamp, row.candidate.symbol, row.candidate.family.value, row.candidate.side))
    ledger.sort(key=lambda row: (row["timestamp"], row["symbol"], row["family"], row["side"]))
    return scored, ledger


def execution_config(extra_round_trip_bps: float) -> CoarseExecutionConfig:
    # Extra cost is split evenly across entry and exit and added to both maker and
    # taker rates. Base slippage/spread assumptions stay unchanged.
    extra_one_way = extra_round_trip_bps / 2.0 / 10_000.0
    base = CoarseExecutionConfig()
    return CoarseExecutionConfig(
        activation_latency_ms=base.activation_latency_ms,
        maker_fee_rate=base.maker_fee_rate + extra_one_way,
        taker_fee_rate=base.taker_fee_rate + extra_one_way,
        market_slippage_bps=base.market_slippage_bps,
        stop_slippage_bps=base.stop_slippage_bps,
        passive_requires_trade_through=base.passive_requires_trade_through,
        minimum_spread_bps=base.minimum_spread_bps,
    )


def final_prices(account: Any, execution: dict[str, pd.DataFrame], end: pd.Timestamp, config: CoarseExecutionConfig) -> tuple[float, float | None]:
    if account.position is not None:
        frame = execution[account.position.candidate.symbol]
        eligible = frame.loc[pd.to_datetime(frame["bar_start"], utc=True) < end]
        row = eligible.iloc[-1]
        mark = float(row.get("mark_close", row["close"]))
        return mark, coarse_closeout_price(row, account.position.side, config)
    mark = 0.0
    for frame in execution.values():
        eligible = frame.loc[pd.to_datetime(frame["bar_start"], utc=True) < end]
        if not eligible.empty:
            row = eligible.iloc[-1]
            mark = float(row.get("mark_close", row["close"]))
    return mark, None


def winner_removed_path(trades: list[Any], initial_nav: float, calendar_days: int) -> dict[str, Any]:
    if not trades:
        return {"end_nav": initial_nav, "account_multiple": 1.0, "geometric_daily_growth": 0.0, "maximum_drawdown": 0.0}
    remove = max(range(len(trades)), key=lambda i: float(trades[i].net_pnl))
    nav = peak = float(initial_nav)
    mdd = 0.0
    for index, trade in enumerate(trades):
        if index == remove:
            continue
        nav *= 1.0 + float(trade.net_return_on_entry_equity)
        peak = max(peak, nav)
        mdd = max(mdd, 1.0 - nav / peak)
    growth = -1.0 if nav <= 0 else exp(log(nav / initial_nav) / calendar_days) - 1.0
    return {
        "removed_trade_index": remove,
        "removed_trade_net_pnl": float(trades[remove].net_pnl),
        "end_nav": nav,
        "account_multiple": nav / initial_nav,
        "geometric_daily_growth": growth,
        "maximum_drawdown": mdd,
    }


def serialise(value: Any) -> Any:
    if is_dataclass(value):
        return {key: serialise(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): serialise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialise(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    end = pd.Timestamp("2024-07-01T00:00:00Z")
    decision, execution, funding = load_canonical_frames(
        args.data_root, args.repo_root, PRIMARY, ("PRE_2024_2023", "2024_H1")
    )
    candidates: list[Any] = []
    diagnostics: dict[str, dict[str, int]] = {}
    for symbol, frame in sorted(decision.items()):
        features = build_corpus_features(frame, FeatureConfig())
        rows, row_diagnostics = generate_corpus_candidates_with_diagnostics(features, symbol)
        diagnostics[symbol] = row_diagnostics
        candidates.extend(row for row in rows if start <= row.timestamp < end)
    candidates.sort(key=lambda row: (row.timestamp, row.symbol, row.family.value, row.side))

    gate_counts = {name: 0 for name in ("G1", "G2", "G3", "G4")}
    overlap_count = 0
    for candidate in candidates:
        matches = matching_gates(candidate)
        for gate, _, _ in matches:
            gate_counts[gate] += 1
        overlap_count += int(len(matches) > 1)

    results: list[dict[str, Any]] = []
    candidate_ledgers: dict[str, list[dict[str, Any]]] = {}
    for spec in CONFIGURATIONS:
        scored, ledger = score_for_portfolio(candidates, set(spec["gates"]))
        candidate_ledgers[spec["id"]] = ledger
        for stress in STRESS_ROUND_TRIP_BPS:
            config = execution_config(stress)
            account = CoarseEventReplay(execution, config).run(
                scored,
                GlobalSlotPolicy(),
                RiskConfig(float(spec["risk"]), float(spec["leverage"]), 0.001, 0.001),
                start,
                end,
                initial_nav=10_000.0,
                funding=funding,
                instrument_rules={"BTCUSDT": (0.001, 0.001), "ETHUSDT": (0.01, 0.01)},
            )
            mark, closeout = final_prices(account, execution, end, config)
            metrics = summarize_account(
                account,
                start,
                end,
                mark,
                final_closeout_price=closeout,
                final_closeout_fee_rate=config.taker_fee_rate if closeout is not None else 0.0,
            )
            result = {
                "configuration": spec,
                "stress_extra_round_trip_bps": stress,
                "eligible_candidate_count": len(scored),
                "metrics": metrics.as_dict(),
                "winner_removed_path": winner_removed_path(account.closed_trades, 10_000.0, 182),
                "closed_trades": [serialise(row) for row in account.closed_trades],
                "daily_nav": [serialise(row) for row in account.daily_nav],
                "fills": [serialise(row) for row in account.fills],
                "invalid_reason": account.invalid_reason,
            }
            results.append(result)

    base_rows = [row for row in results if row["stress_extra_round_trip_bps"] == 0.0]
    valid_base = [row for row in base_rows if not row["metrics"]["liquidated_or_invalid"] and row["metrics"]["end_nav"] > 0]
    best_diagnostic = max(
        valid_base,
        key=lambda row: (
            row["metrics"]["geometric_daily_growth"],
            row["winner_removed_path"]["geometric_daily_growth"],
            -row["metrics"]["maximum_drawdown"],
        ),
        default=None,
    )
    primary = next(row for row in base_rows if bool(row["configuration"]["primary"]))
    payload = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "stage": "2024_H1_FROZEN_2023_SELECTED_STRUCTURAL_ALPHA_1M_PROVISIONAL",
        "corpus_contract": "178_NON_MEMBERSHIP_TRANSCRIPTS_MEMBERSHIP_EXCLUDED",
        "selection_authority": "ALL_GATES_PORTFOLIOS_RISK_AND_PRIORITY_FIXED_FROM_2023_ONLY",
        "scientific_source_commit": args.scientific_source_commit,
        "canonical_source_commit": args.canonical_source_commit,
        "evaluation_start": start,
        "evaluation_end_exclusive": end,
        "structural_candidate_count": len(candidates),
        "gate_counts_before_global_slot": gate_counts,
        "multi_gate_overlap_count": overlap_count,
        "candidate_generation_diagnostics": diagnostics,
        "primary_result_id": "PRIMARY_P123_R30_L100",
        "primary_base_result": primary,
        "best_h1_diagnostic_not_selection_authority": best_diagnostic,
        "target_reached_by_primary_base": bool(primary["metrics"]["geometric_daily_growth"] >= 0.01),
        "target_reached_after_primary_winner_removal": bool(primary["winner_removed_path"]["geometric_daily_growth"] >= 0.01),
        "results": results,
        "candidate_ledgers": candidate_ledgers,
        "ranking_effect": "PROVISIONAL_NOT_EVENT_TAPE_VALIDATED",
    }
    path = args.output / "YTT_178_FROZEN_H1_RESULT.json"
    path.write_text(json.dumps(serialise(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = pd.DataFrame([
        {
            "configuration": row["configuration"]["id"],
            "primary": row["configuration"]["primary"],
            "risk": row["configuration"]["risk"],
            "leverage": row["configuration"]["leverage"],
            "stress_extra_round_trip_bps": row["stress_extra_round_trip_bps"],
            **row["metrics"],
            "winner_removed_geometric_daily_growth": row["winner_removed_path"]["geometric_daily_growth"],
            "winner_removed_multiple": row["winner_removed_path"]["account_multiple"],
        }
        for row in results
    ])
    summary.to_csv(args.output / "YTT_178_FROZEN_H1_SUMMARY.csv", index=False)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scientific-source-commit", required=True)
    parser.add_argument("--canonical-source-commit", required=True)
    payload = run(parser.parse_args())
    primary = payload["primary_base_result"]
    print(json.dumps({
        "primary": primary["configuration"]["id"],
        "metrics": primary["metrics"],
        "winner_removed": primary["winner_removed_path"],
        "target_reached": payload["target_reached_by_primary_base"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
