from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RANKING_PATH = ROOT / "control" / "ranking.json"
STATE_PATH = ROOT / "control" / "current-state.md"
RESULT_ROOT = ROOT / "research_results" / "rank_contract_reconcile_20260726"
REPRO_PATH = RESULT_ROOT / "INDEPENDENT_REPRODUCTION_ALL_BREAKOUT.json"
DECISION_PATH = RESULT_ROOT / "DECISION.json"
RESULT_PATH = RESULT_ROOT / "RESULT.json"
CORRECTION_PATH = RESULT_ROOT / "RANKING_CORRECTION_002.json"
UPDATED_AT = "2026-07-26T20:39:00+09:00"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def candidate_row(
    rank: int,
    label: str,
    result_id: str,
    growth: float,
    confidence: str,
    status: str,
) -> dict[str, Any]:
    return {
        "rank": rank,
        "candidate_label": label,
        "source_result_id": result_id,
        "geometric_daily_growth": growth,
        "target_gap": 0.01 - growth,
        "comparison_confidence": confidence,
        "comparison_status": status,
    }


def main() -> int:
    ranking = load_json(RANKING_PATH)
    repro = load_json(REPRO_PATH)
    decision = load_json(DECISION_PATH)
    result = load_json(RESULT_PATH)

    if int(ranking["revision"]) not in (13, 14):
        raise RuntimeError(f"unexpected ranking revision {ranking['revision']}")
    if repro["candidate"]["mode"] != "all":
        raise RuntimeError("reproduction is not all-breakout")
    if not repro["cross_check"]["all_breakout_growth_matches_compact_matched_comparator"]:
        raise RuntimeError("all-breakout compact-result cross-check failed")

    p12 = repro["paths"]["12bps"]
    p18 = repro["paths"]["18bps"]
    p24 = repro["paths"]["24bps"]
    expected_growth = 0.0007001887213879954
    if abs(float(p24["geometric_daily_growth"]) - expected_growth) > 1e-15:
        raise RuntimeError("unexpected all-breakout 24-bps growth")

    old_first = copy.deepcopy(ranking["first_place"])
    if old_first["source_result_id"] != "RES-20260726-DONCHIAN-DEPENDENCE-001":
        raise RuntimeError("revision-13 first place is not Donchian")

    ranking["first_place"] = {
        "rank": 1,
        "first_place_id": "FIRST-20260726-DONCHIAN-ALL-A70626D9",
        "candidate_type": "STRATEGY",
        "source_result_id": "RES-20260726-DONCHIAN-DEPENDENCE-001",
        "source_pull_request": "https://github.com/umtong/SMC_ICT_2_LIVE/pull/61",
        "qualification_stage": "PRELIMINARY_CAUSAL_BINANCE_PROXY",
        "comparison_confidence": "VERY_LOW",
        "target_status": "NOT_MET",
        "selection_reason": (
            "The former dynamic state-exit is removed because its immutable engine "
            "uses a prohibited elapsed-time liquidation. Independent reproduction "
            "from the exact registered snapshot and Donchian source recovered the "
            "matched all-breakout comparator's complete account metrics. Its 24-bp "
            "geometric daily growth is the highest recorded current-contract-compatible "
            "strategy result. Proxy execution, omitted funding, unopened later periods "
            "and extreme winner concentration are disclosed rather than used to suppress "
            "the provisional rank."
        ),
        "metrics": {
            "candidate_id": "a70626d9e484285f2cb4|all",
            "family": "donchian_all_breakout_60m_entry96_exit48",
            "base_cost_bps": 24,
            "geometric_daily_growth": p24["geometric_daily_growth"],
            "target_geometric_daily_growth": 0.01,
            "target_gap": 0.01 - p24["geometric_daily_growth"],
            "target_fraction": p24["geometric_daily_growth"] / 0.01,
            "target_multiple_required": 0.01 / p24["geometric_daily_growth"],
            "total_return": p24["total_return"],
            "maximum_drawdown": p24["maximum_drawdown"],
            "trade_count": p24["trade_count"],
            "profit_factor": p24["profit_factor"],
            "median_account_return_bps": p24["median_account_return_bps"],
            "mean_account_return_bps": p24["mean_account_return_bps"],
            "win_rate": p24["win_rate"],
            "top5_positive_share": p24["top5_positive_share"],
            "top10pct_removed_return": p24["top10pct_removed_return"],
            "h1_return": p24["h1_return"],
            "h2_return": p24["h2_return"],
            "median_holding_hours": p24["median_holding_hours"],
            "maximum_leverage_used": p24["maximum_leverage_used"],
            "actual_funding_included": False,
            "bybit_execution_replayed": False,
            "exit_reason_counts": p24["exit_reason_counts"],
            "symbol_counts": p24["symbol_counts"],
            "geometric_daily_growth_12bps": p12["geometric_daily_growth"],
            "geometric_daily_growth_18bps": p18["geometric_daily_growth"],
        },
        "sequential_evidence": {
            "development_period": "2023",
            "development_gate_pass_count": 0,
            "selection_2024_opened": False,
            "confirmation_2025_opened": False,
            "2026_opened": False,
        },
        "known_weaknesses": [
            "Binance USD-M price proxy rather than exact Bybit execution replay.",
            "Historical funding was omitted after the fatal development-gate failure.",
            "The completed-bar approximation does not reproduce original stop-order tick triggering.",
            "Removing the largest 10% winning trades changes the 24-bp return to -26.9469%.",
            "The median account return is -50 bps and the win rate is 20.20%.",
            "The five largest winners contribute 64.22% of positive PnL.",
            "No 2024 or later interval was opened.",
            "It is a non-ML baseline and cannot satisfy the final system's ML requirement.",
            "Daily growth remains far below the 1% target.",
        ],
    }

    old_rows = copy.deepcopy(ranking["ranked_candidates"])
    lower_rows = [
        row
        for row in old_rows
        if not (
            row["source_result_id"] == "RES-20260726-DONCHIAN-DEPENDENCE-001"
            and "after_loser" in row["candidate_label"]
        )
    ]
    new_rows = [
        candidate_row(
            1,
            "Donchian all-breakout 60m/96/48 a70626d9e484285f2cb4",
            "RES-20260726-DONCHIAN-DEPENDENCE-001",
            p24["geometric_daily_growth"],
            "VERY_LOW",
            "PROVISIONAL_24BPS_BINANCE_PROXY_NO_FUNDING_NO_BYBIT_OOS_FULL_METRICS_REPRODUCED",
        ),
        candidate_row(
            2,
            "Donchian after_loser 60m/96/48/240 a70626d9e484285f2cb4",
            "RES-20260726-DONCHIAN-DEPENDENCE-001",
            0.0006318446194384375,
            "VERY_LOW",
            "PROVISIONAL_24BPS_BINANCE_PROXY_NO_FUNDING_NO_BYBIT_OOS",
        ),
    ]
    for row in lower_rows:
        item = copy.deepcopy(row)
        item["rank"] = int(item["rank"]) + 1
        new_rows.append(item)
    if [row["rank"] for row in new_rows] != list(range(1, len(new_rows) + 1)):
        raise RuntimeError("ranking rows are not contiguous")
    ranking["ranked_candidates"] = new_rows
    ranking["ranking_id"] = "STRATEGY-RANKING-20260726-R14"
    ranking["revision"] = 14
    ranking["updated_at"] = UPDATED_AT
    ranking["reconciliation_notes"] = [
        "Removed the former first place because its immutable simulation has a fixed hold_bars horizon exit, prohibited by the current project contract.",
        "Recovered the Donchian all-breakout comparator's full 12/18/24-bp account metrics from the exact registered snapshot and source; it is provisional rank 1 at 24 bps.",
        "Moved the Donchian after-loser path to rank 2 because its 24-bp growth is lower and the claimed conditional dependence was not established.",
        "Both Donchian paths are Binance proxies without historical funding or Bybit OOS and collapse after top-10% winner removal.",
        "Lower legacy ranks remain provisional; candidates whose original contracts may contain horizon exits require separate evidence-only audits.",
        "Target status and live-order permission remain unchanged.",
    ]
    write_json(RANKING_PATH, ranking)

    decision["decision"] = "REMOVE_FORMER_FIRST_AND_PROMOTE_DONCHIAN_ALL_BREAKOUT_PROVISIONALLY"
    decision["new_first"] = {
        "first_place_id": "FIRST-20260726-DONCHIAN-ALL-A70626D9",
        "candidate_id": "a70626d9e484285f2cb4|all",
        "cost_bps": 24,
        "geometric_daily_growth": p24["geometric_daily_growth"],
        "target_gap": 0.01 - p24["geometric_daily_growth"],
        "total_return": p24["total_return"],
        "maximum_drawdown": p24["maximum_drawdown"],
        "trade_count": p24["trade_count"],
        "profit_factor": p24["profit_factor"],
        "median_account_return_bps": p24["median_account_return_bps"],
        "top5_positive_share": p24["top5_positive_share"],
        "top10pct_removed_return": p24["top10pct_removed_return"],
        "comparison_confidence": "VERY_LOW",
        "source_result_id": "RES-20260726-DONCHIAN-DEPENDENCE-001",
        "source_result_blob_sha": "31453a4b313412549f9d78a505d1329d4528436a",
        "independent_reproduction": str(REPRO_PATH.relative_to(ROOT)),
        "ranking_basis": "Highest fully reproduced 24-bp growth among current-contract-compatible strategies.",
    }
    decision["second_place"] = {
        "first_place_id": "SECOND-20260726-DONCHIAN-AFTER-LOSER-A70626D9",
        "candidate_id": "a70626d9e484285f2cb4|after_loser",
        "geometric_daily_growth_24bps": 0.0006318446194384375,
        "reason": "Lower growth than its all-breakout comparator; dependence effect not established.",
    }
    decision["new_ranking_revision"] = 14
    decision["updated_at"] = UPDATED_AT
    write_json(DECISION_PATH, decision)

    result["new_current_first_place"] = copy.deepcopy(ranking["first_place"])
    result["second_place_full_metrics"] = {
        "first_place_id": "SECOND-20260726-DONCHIAN-AFTER-LOSER-A70626D9",
        "candidate_id": "a70626d9e484285f2cb4|after_loser",
        "source_result_id": "RES-20260726-DONCHIAN-DEPENDENCE-001",
        "base_cost_bps": 24,
        "geometric_daily_growth": 0.0006318446194384375,
        "target_gap": 0.009368155380561563,
        "total_return": 0.259293006748736,
        "maximum_drawdown": 0.1102976476441001,
        "trade_count": 89,
        "profit_factor": 1.6226240830708625,
        "median_account_return_bps": -50.0,
        "top5_positive_share": 0.6735035238367593,
        "top10pct_removed_return": -0.26306178630598,
        "exit_contract_status": "PASS_CURRENT_CONTRACT",
    }
    result["ranking_decision"]["new_first_place_id"] = "FIRST-20260726-DONCHIAN-ALL-A70626D9"
    result["ranking_decision"]["new_ranking_revision"] = 14
    result["independent_reproduction"] = str(REPRO_PATH.relative_to(ROOT))
    result["updated_at"] = UPDATED_AT
    write_json(RESULT_PATH, result)

    correction = {
        "schema_version": 1,
        "correction_id": "CORRECTION-20260726-RANK-ALL-BREAKOUT-METRICS-002",
        "claim_id": "CLM-20260726-2014-RANK-CONTRACT-RECONCILE-001",
        "status": "PASS_STATE_RECONCILIATION",
        "previous_revision": 13,
        "new_revision": 14,
        "previous_first_place": old_first["first_place_id"],
        "new_first_place": "FIRST-20260726-DONCHIAN-ALL-A70626D9",
        "reason": "The all-breakout comparator's complete account metrics were independently reproduced from the exact registered snapshot and source, resolving revision 13's RESULT/DECISION inconsistency.",
        "market_data_opened": False,
        "strategy_replayed_for_selection": False,
        "parameters_searched": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
        "updated_at": UPDATED_AT,
    }
    write_json(CORRECTION_PATH, correction)

    state = f"""# Current state

- revision: 14
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-DONCHIAN-ALL-A70626D9`
- first-place stage: `PRELIMINARY_CAUSAL_BINANCE_PROXY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Ranking correction

The former first place, dynamic state-exit `021fbab613517a31ad98`, is removed from the active ranking because its immutable engine exits surviving trades after a fixed `hold_bars` horizon. That elapsed-time liquidation violates the current project contract.

Revision 13 initially placed the fully recorded Donchian after-loser path first while its higher-growth matched all-breakout comparator lacked expanded metrics in the compact result. Revision 14 independently reproduced the comparator from the exact registered snapshot and source, so incomplete evidence no longer justifies suppressing it.

## Current first place

The provisional first place is Donchian all-breakout `a70626d9e484285f2cb4|all`.

- rule: completed 60-minute Donchian channel, entry lookback 96, exit channel 48, all breakouts
- 12-bps geometric daily growth: `{100*p12['geometric_daily_growth']:.7f}%`
- 18-bps geometric daily growth: `{100*p18['geometric_daily_growth']:.7f}%`
- 24-bps geometric daily growth: `{100*p24['geometric_daily_growth']:.7f}%`
- 1% target gap at 24 bps: `{100*(0.01-p24['geometric_daily_growth']):.7f} percentage points per UTC calendar day`
- total return at 24 bps: `{100*p24['total_return']:+.4f}%`
- maximum drawdown at 24 bps: `{100*p24['maximum_drawdown']:.4f}%`
- trades: `{p24['trade_count']}`
- profit factor at 24 bps: `{p24['profit_factor']:.4f}`
- median account return: `{p24['median_account_return_bps']:.2f} bps`
- win rate: `{100*p24['win_rate']:.2f}%`
- top-five positive-PnL share: `{100*p24['top5_positive_share']:.2f}%`
- top-10%-winner-removed return: `{100*p24['top10pct_removed_return']:.4f}%`
- first-half / second-half return: `{100*p24['h1_return']:+.4f}% / {100*p24['h2_return']:+.4f}%`

The comparison confidence is `VERY_LOW`: Binance proxy, funding omitted, no exact Bybit replay, no 2024+, and severe positive-tail dependence. It is also non-ML, so it is only the current performance benchmark, not a final-system candidate.

## Current provisional ranks

1. Donchian all-breakout — `{100*p24['geometric_daily_growth']:.7f}%` daily at 24 bps.
2. Donchian after-loser — `0.0631845%` daily at 24 bps.
3. aligned continuation — `0.0227977%` daily; legacy exit audit pending.
4. perp overshoot reversal — `0.0118976%` daily; legacy exit audit pending.
5. liquidation exhaustion reversal — `0.00358316%` daily, very sparse.
6. DVOL low-VRP residual continuation — `0.0034002%` daily; legacy exit audit pending.
7. high-resistance sweep — `0.0024555%` daily.
8. fragmented-flow reversal — `0.0020533%` daily, four trades.

## Current objective

Do not protect the new first place. It remains roughly `{0.01/p24['geometric_daily_growth']:.2f}` times short of the 1% daily-growth objective and fails concentration, exact-Bybit, funding, sequential-OOS and ML requirements.

Consume the already-running high-information ML paths with strategy-defined exits:

- Coinbase aggressive spot flow into delayed executable Bybit BBO;
- Bybit mark/index acceptance after an executable liquidity raid;
- funding-boundary movement-hazard OCO;
- external forced-flow paths only when source gates pass.

A positive hard-valid result is inserted immediately. A negative result is retired without model, feature, threshold, stop, risk or leverage rescue.

## Next exact action

Finish Coinbase and mark/index ML. In parallel, complete exact-arrival V5D. Any candidate exceeding `{100*p24['geometric_daily_growth']:.7f}%` daily after comparable realistic cost and current-contract exits takes first place immediately.
"""
    STATE_PATH.write_text(state, encoding="utf-8")

    check = load_json(RANKING_PATH)
    if check["first_place"]["first_place_id"] != "FIRST-20260726-DONCHIAN-ALL-A70626D9":
        raise RuntimeError("first place correction did not persist")
    if check["ranked_candidates"][1]["rank"] != 2:
        raise RuntimeError("second-place shift did not persist")
    print(
        json.dumps(
            {
                "revision": check["revision"],
                "first_place": check["first_place"]["first_place_id"],
                "growth_24bps": check["first_place"]["metrics"]["geometric_daily_growth"],
                "target_gap": check["first_place"]["metrics"]["target_gap"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
