from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import strict_guard_v4 as v4

base = v4.base
v3 = v4.v3
ENGINE = "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_PROFIT_FIRST_V5"
CORRECTION_ID = "CORRECTION-20260727-ML-STABLECOIN-PROFIT-FIRST-ADVANCEMENT-005"
CORRECTION_FILE = Path(__file__).with_name(
    "CORRECTION_005_PROFIT_FIRST_ADVANCEMENT_BEFORE_OUTCOME.json"
)
RISKS = (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.20, 0.30, 0.40, 0.60)
CAPS = (1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0, 100.0)


def _load_correction() -> dict[str, Any]:
    value = json.loads(CORRECTION_FILE.read_text(encoding="utf-8"))
    if value["correction_id"] != CORRECTION_ID:
        raise AssertionError(value["correction_id"])
    if value["timing"] != (
        "BEFORE_ANY_DECISION_READY_SOURCE_RESULT_MARKET_ROW_LABEL_MODEL_"
        "TRADE_PNL_OR_OFFICIAL_INTERVAL"
    ):
        raise AssertionError(value["timing"])
    if any(bool(value["observed_before_correction"][key]) for key in (
        "source_decision",
        "market_archive_opened",
        "label_computed",
        "model_fitted",
        "trade_or_pnl_opened",
        "official_2024_2026_opened",
        "credentials_used",
        "orders_submitted",
    )):
        raise AssertionError("profit-first correction was not outcome-sealed")
    return value


def select_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [
        candidate
        for candidate in candidates
        if candidate["liquidation"] is False and float(candidate["growth"]) > 0.0
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda candidate: (
            float(candidate["growth"]),
            float(candidate["winner_removed_growth"]),
            -float(candidate["mdd"]),
        ),
    )


def profit_first_risk_search(
    rows: pd.DataFrame,
    probabilities: np.ndarray,
    bars: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for risk in RISKS:
        for cap in CAPS:
            trades = base.route(
                rows,
                probabilities,
                bars,
                funding,
                base.PRIMARY_COST_BPS,
            )
            metrics = base.replay(
                trades,
                base.PRIMARY_COST_BPS,
                "2023-01-01",
                "2024-01-01",
                risk,
                cap,
            )
            winner_removed, excluded = base.winner_removed(
                rows,
                probabilities,
                bars,
                funding,
                base.PRIMARY_COST_BPS,
                "2023-01-01",
                "2024-01-01",
                risk,
                cap,
            )
            candidates.append(
                {
                    "risk": risk,
                    "notional_cap": cap,
                    "growth": metrics["geometric_calendar_day_growth"],
                    "return": metrics["total_return"],
                    "mdd": metrics["maximum_drawdown"],
                    "liquidation": bool(metrics["liquidation"]),
                    "winner_removed_growth": winner_removed[
                        "geometric_calendar_day_growth"
                    ],
                    "winner_removed_return": winner_removed["total_return"],
                    "removed_event_ids": excluded,
                }
            )
    selected = select_candidate(candidates)
    return {
        "selection_rule": (
            "MAX_POSITIVE_24BP_GEOMETRIC_GROWTH_NO_LIQUIDATION;_"
            "WINNER_REMOVAL_GROWTH_AND_LOWER_MDD_TIEBREAK_ONLY"
        ),
        "winner_removal_is_eligibility_gate": False,
        "candidate_count": len(candidates),
        "eligible_count": sum(
            candidate["liquidation"] is False
            and float(candidate["growth"]) > 0.0
            for candidate in candidates
        ),
        "selected": selected,
        "candidates": candidates,
    }


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _compact(child)
            for key, child in value.items()
            if key not in {"trade_ledger", "ledger"}
        }
    if isinstance(value, list):
        return [_compact(child) for child in value]
    return value


def _write_initial_result(output: Path, payload: dict[str, Any]) -> None:
    v3._write_json(output / "FULL_RESULT.json", payload)
    v3._write_json(output / "RESULT.json", _compact(payload))


def _finalize(output: Path) -> dict[str, Any]:
    audited = v4.audit(output)
    result_path = output / "RESULT.json"
    full_path = output / "FULL_RESULT.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    full = json.loads(full_path.read_text(encoding="utf-8"))
    guard = {
        "correction_id": CORRECTION_ID,
        "confirmation_opens_calendar_2023": True,
        "confirmation_prediction_and_robustness_metrics_are_diagnostics": True,
        "calendar_2023_base_gate": (
            "POSITIVE_TOTAL_RETURN_AT_24BP_AND_NO_FORCED_LIQUIDATION"
        ),
        "risk_search_eligibility": "POSITIVE_24BP_GROWTH_AND_NO_LIQUIDATION",
        "winner_removal_is_diagnostic_and_tiebreak_only": True,
        "official_next_stage": (
            "EXACT_BYBIT_RECONSTRUCTION_THEN_OFFICIAL_2024H1_IMMEDIATELY"
        ),
        "fatal_validity_violation": False,
    }
    for payload in (result, full):
        payload["engine"] = ENGINE
        payload["profit_first_advancement_guard"] = guard
        payload["official_2024h1_opened"] = False
        payload["official_2024_2026_opened"] = False
        payload["orders_submitted"] = False
    result["status"] = full["status"]
    (output / CORRECTION_FILE.name).write_bytes(CORRECTION_FILE.read_bytes())
    v3._write_json(result_path, result)
    v3._write_json(full_path, full)
    v3._refresh_hashes(output)
    return {
        "strict_causal_guard": audited["strict_causal_guard"],
        "v4_account_guard": audited["v4_account_guard"],
        "profit_first_advancement_guard": guard,
    }


def run_profit_first(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    events = base.load_events(args.events)
    if any(
        pd.to_datetime(events["block_timestamp"], unit="s", utc=True).dt.year
        >= 2024
    ):
        raise AssertionError("pre-2024 stage received 2024 event")

    base.acquire_binance(args.market_cache, "2020-12", "2023-12")
    bars, funding = base.load_market(args.market_cache, "2020-12", "2023-12")
    rows12 = v4.build_rows(events, bars, funding, 12)
    rows64 = v4.build_rows(events, bars, funding, 64)

    if rows12.empty:
        payload = {
            "schema_version": 1,
            "claim_id": base.CLAIM_ID,
            "engine": ENGINE,
            "status": "PRE2024_MODEL_POPULATION_FAILURE",
            "source_event_count": int(len(events)),
            "row_count_12": 0,
            "row_count_64": int(len(rows64)),
            "model_error": "NO_ECONOMICALLY_EVALUABLE_ROWS",
            "development_opened": False,
            "development_gate": {
                "model_population_valid": False,
                "all": False,
            },
            "risk_search": None,
            "official_2024h1_opened": False,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        }
        _write_initial_result(output, payload)
        guards = _finalize(output)
        return {"result": payload, "guards": guards}

    try:
        model, calibrator, median_map, medians = base.fit_model(rows12)
    except Exception as error:
        payload = {
            "schema_version": 1,
            "claim_id": base.CLAIM_ID,
            "engine": ENGINE,
            "status": "PRE2024_MODEL_POPULATION_FAILURE",
            "source_event_count": int(len(events)),
            "row_count_12": int(len(rows12)),
            "row_count_64": int(len(rows64)),
            "feature_names": list(base.FEATURES),
            "model_error": repr(error),
            "development_opened": False,
            "development_gate": {
                "model_population_valid": False,
                "all": False,
            },
            "risk_search": None,
            "official_2024h1_opened": False,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        }
        _write_initial_result(output, payload)
        guards = _finalize(output)
        return {"result": payload, "guards": guards}

    probabilities12 = base.probabilities(model, calibrator, medians, rows12)
    probabilities64 = (
        base.probabilities(model, calibrator, medians, rows64)
        if not rows64.empty
        else np.array([], dtype=float)
    )
    probability_map12 = dict(
        zip(rows12.index.to_list(), probabilities12.tolist())
    )

    confirmation_rows = base.segment(
        rows12, "2022-07-01", "2023-01-01"
    )
    confirmation_probabilities = np.array(
        [probability_map12[index] for index in confirmation_rows.index],
        dtype=float,
    )
    confirmation = base.evaluate_stage(
        "2022H2_CONFIRMATION_12_BLOCK_DIAGNOSTIC",
        confirmation_rows,
        confirmation_probabilities,
        bars,
        funding,
        "2022-07-01",
        "2023-01-01",
    )
    confirmation_diagnostics = base.confirmation_gate(confirmation)
    confirmation_diagnostics["all"] = all(
        confirmation_diagnostics.values()
    )

    stress = None
    if not rows64.empty:
        probability_map64 = dict(
            zip(rows64.index.to_list(), probabilities64.tolist())
        )
        stress_rows = base.segment(rows64, "2022-07-01", "2023-01-01")
        stress_probabilities = np.array(
            [probability_map64[index] for index in stress_rows.index],
            dtype=float,
        )
        stress = base.evaluate_stage(
            "2022H2_CONFIRMATION_64_BLOCK_STRESS_DIAGNOSTIC",
            stress_rows,
            stress_probabilities,
            bars,
            funding,
            "2022-07-01",
            "2023-01-01",
        )

    development_rows = base.segment(rows12, "2023-01-01", "2024-01-01")
    development_probabilities = np.array(
        [probability_map12[index] for index in development_rows.index],
        dtype=float,
    )
    development = base.evaluate_stage(
        "2023_DEVELOPMENT_PROFIT_FIRST",
        development_rows,
        development_probabilities,
        bars,
        funding,
        "2023-01-01",
        "2024-01-01",
    )
    development_diagnostics = base.development_gate(development)
    development_diagnostics["all"] = all(development_diagnostics.values())

    primary = development["costs"][str(int(base.PRIMARY_COST_BPS))]
    positive_base = float(primary["total_return"]) > 0.0
    base_survived = bool(primary["liquidation"]) is False
    risk_search = (
        profit_first_risk_search(
            development_rows,
            development_probabilities,
            bars,
            funding,
        )
        if positive_base and base_survived
        else None
    )
    selected = risk_search["selected"] if risk_search is not None else None
    advancement_gate = {
        "model_population_valid": True,
        "calendar_2023_positive_total_return_at_24bps": positive_base,
        "calendar_2023_no_forced_liquidation_at_base_sizing": base_survived,
        "positive_no_liquidation_risk_path_selected": selected is not None,
    }
    advancement_gate["all"] = all(advancement_gate.values())
    status = (
        "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
        if advancement_gate["all"]
        else "PRE2024_BELOW_GATE"
    )

    payload = {
        "schema_version": 1,
        "claim_id": base.CLAIM_ID,
        "engine": ENGINE,
        "status": status,
        "source_event_count": int(len(events)),
        "row_count_12": int(len(rows12)),
        "row_count_64": int(len(rows64)),
        "feature_names": list(base.FEATURES),
        "feature_medians": median_map,
        "model": {
            "family": "HistGradientBoostingClassifier",
            "isotonic": calibrator is not None,
            "profit_first_policy_changes_model": False,
        },
        "confirmation": confirmation,
        "confirmation_diagnostics_not_gate": confirmation_diagnostics,
        "confirmation_64_block_stress_diagnostic": stress,
        "development_opened": True,
        "development": development,
        "development_diagnostics_not_gate": development_diagnostics,
        "development_gate": advancement_gate,
        "risk_search": risk_search,
        "official_2024h1_opened": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    _write_initial_result(output, payload)
    guards = _finalize(output)
    final_result = json.loads(
        (output / "RESULT.json").read_text(encoding="utf-8")
    )
    return {"result": final_result, "guards": guards}


def self_test() -> None:
    _load_correction()
    v4.self_test()
    candidates = [
        {
            "growth": 0.002,
            "winner_removed_growth": -0.001,
            "mdd": 0.10,
            "liquidation": False,
        },
        {
            "growth": 0.001,
            "winner_removed_growth": 0.0008,
            "mdd": 0.05,
            "liquidation": False,
        },
        {
            "growth": 0.5,
            "winner_removed_growth": 0.5,
            "mdd": 1.0,
            "liquidation": True,
        },
    ]
    selected = select_candidate(candidates)
    if selected is not candidates[0]:
        raise AssertionError(selected)
    if select_candidate(
        [
            {
                "growth": -0.001,
                "winner_removed_growth": 0.1,
                "mdd": 0.1,
                "liquidation": False,
            }
        ]
    ) is not None:
        raise AssertionError("negative-growth path became eligible")
    print("stablecoin profit-first V5 advancement self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--events", type=Path, required=True)
    run_parser.add_argument("--market-cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _load_correction()
    v4._load_correction()
    v4._patch()
    if args.command == "self-test":
        self_test()
        return 0
    outcome = run_profit_first(args)
    print(json.dumps(outcome["guards"], indent=2, sort_keys=True))
    status = outcome["result"].get("status")
    return (
        0
        if status == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
