from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

import run_ml_screen as base
import run_ml_screen_v4 as winner_patch

ROOT = Path(__file__).resolve().parent
AMENDMENT_004_PATH = ROOT / "amendment_004_five_feature_annual_oos.json"
TRAIN_CUTOFF = pd.Timestamp("2021-12-31T23:59:59Z")
REFIT_CUTOFF = pd.Timestamp("2022-12-31T23:59:59Z")
MODEL_ID = "CME_GAP_COMPETING_RISK_LOGIT_V2"
POLICY_ID = hashlib.sha256(MODEL_ID.encode()).hexdigest()[:20]
ORIGINAL_FEATURE_NAMES = tuple(base.FEATURE_NAMES)
FIVE_FEATURE_NAMES = (
    "gap_signed_atr",
    "residual_in_gap_direction",
    "response_in_gap_direction_atr",
    "rebalance_progress",
    "log_continuation_to_rebalance_distance",
)
FIVE_FEATURE_INDEX = tuple(ORIGINAL_FEATURE_NAMES.index(name) for name in FIVE_FEATURE_NAMES)
ORIGINAL_BUILD_OPPORTUNITIES = base.build_opportunities
ORIGINAL_LOAD_STAGE = base.core.load_stage


def resolved_by(item: base.Opportunity, cutoff: pd.Timestamp) -> bool:
    return (
        item.continuation_label in (0, 1)
        and item.resolution_ts is not None
        and pd.Timestamp(item.resolution_ts) <= cutoff
    )


def load_stage_with_turnover_alias(*args, **kwargs):
    cme_by_symbol, bars_by_symbol, funding_by_symbol, records = ORIGINAL_LOAD_STAGE(
        *args, **kwargs
    )
    for symbol, frame in bars_by_symbol.items():
        if "quote_volume" not in frame.columns:
            if "turnover" not in frame.columns:
                raise KeyError(f"{symbol} has neither quote_volume nor turnover")
            frame["quote_volume"] = frame["turnover"]
        if "turnover" in frame.columns and not frame["quote_volume"].equals(frame["turnover"]):
            raise AssertionError(f"{symbol} turnover alias changed values")
    return cme_by_symbol, bars_by_symbol, funding_by_symbol, records


def build_five_feature_opportunities(
    cme_by_symbol: dict[str, pd.DataFrame],
    bars_by_symbol: dict[str, pd.DataFrame],
) -> list[base.Opportunity]:
    previous_names = base.FEATURE_NAMES
    base.FEATURE_NAMES = ORIGINAL_FEATURE_NAMES
    try:
        full = ORIGINAL_BUILD_OPPORTUNITIES(cme_by_symbol, bars_by_symbol)
    finally:
        base.FEATURE_NAMES = previous_names
    projected: list[base.Opportunity] = []
    for item in full:
        values = tuple(item.feature_values[index] for index in FIVE_FEATURE_INDEX)
        if len(values) != 5:
            raise AssertionError("five-feature projection failed")
        projected.append(replace(item, feature_values=values))
    return projected


def prepare_environment() -> None:
    base.FEATURE_NAMES = FIVE_FEATURE_NAMES
    base.MODEL_ID = MODEL_ID
    base.POLICY_ID = POLICY_ID
    base.core.load_stage = load_stage_with_turnover_alias
    winner_patch.patch_metric()


def training_model_payload(
    model,
    rows: list[base.Opportunity],
    amendment: dict[str, Any],
    cutoff: pd.Timestamp,
) -> dict[str, Any]:
    payload = base.serialize_model(model, rows)
    payload.update({
        "active_amendment_id": amendment["amendment_id"],
        "feature_count": 5,
        "training_label_resolution_cutoff": str(cutoff),
        "training_max_entry_ts": max(str(item.entry_ts) for item in rows),
        "training_max_resolution_ts": max(str(item.resolution_ts) for item in rows),
        "training_model_diagnostics": base.model_diagnostics(model, rows),
        "strategy_pnl_computed_on_training_rows": False,
    })
    return payload


def run(output: Path, cache: Path) -> dict[str, Any]:
    prepare_environment()
    prereg = json.loads(base.PREREG_PATH.read_text(encoding="utf-8"))
    core_amendment = json.loads(base.AMENDMENT_PATH.read_text(encoding="utf-8"))
    amendment = json.loads(AMENDMENT_004_PATH.read_text(encoding="utf-8"))
    if amendment["claim_id"] != prereg["claim_id"]:
        raise ValueError("five-feature amendment claim mismatch")
    if amendment["model_contract"]["model_id"] != MODEL_ID:
        raise ValueError("model version mismatch")
    if amendment["model_contract"]["policy_count"] != 1:
        raise ValueError("active ML policy count is not one")
    if tuple(amendment["simplification"]["retained_features"]) != FIVE_FEATURE_NAMES:
        raise ValueError("five-feature amendment and implementation differ")
    output.mkdir(parents=True, exist_ok=True)

    source_records: list[dict[str, Any]] = []
    stage_outputs: dict[str, Any] = {}
    with base.core.requests.Session() as session:
        session.headers["User-Agent"] = "SMC-ICT-2-LIVE-CME-gap-five-feature-ML/2.0"

        cme_2021, bars_2021, funding_2021, records_2021 = base.core.load_stage(
            session, cache, "fit"
        )
        source_records.extend(records_2021)
        opportunities_2021 = build_five_feature_opportunities(cme_2021, bars_2021)
        training_rows = [
            item for item in opportunities_2021
            if resolved_by(item, TRAIN_CUTOFF)
        ]
        if any(
            item.resolution_ts is None or pd.Timestamp(item.resolution_ts) > TRAIN_CUTOFF
            for item in training_rows
        ):
            raise AssertionError("2021 training label crossed the annual OOS boundary")
        model = base.fit_model(training_rows)
        base.write_json(
            output / "training_model.json",
            training_model_payload(model, training_rows, amendment, TRAIN_CUTOFF),
        )
        base.opportunity_table(training_rows, model).to_csv(
            output / "training_2021_opportunities.csv", index=False
        )

        cme_2022, bars_2022, funding_2022, records_2022 = base.core.load_stage(
            session, cache, "development"
        )
        source_records.extend(records_2022)
        opportunities_2022 = build_five_feature_opportunities(cme_2022, bars_2022)
        development_result = base.evaluate_stage(
            "development", model, opportunities_2022, bars_2022, funding_2022
        )
        stage_outputs["development"] = development_result
        development_pass = bool(development_result["stage_pass"])
        base.opportunity_table(opportunities_2022, model).to_csv(
            output / "development_2022_opportunities.csv", index=False
        )
        base.write_json(
            output / "development_result.json",
            {
                key: value
                for key, value in development_result.items()
                if key != "opportunities"
            },
        )

        confirmation_opened = development_pass
        confirmation_pass = False
        if confirmation_opened:
            refit_rows = [
                item for item in opportunities_2021 + opportunities_2022
                if resolved_by(item, REFIT_CUTOFF)
            ]
            if any(
                item.resolution_ts is None or pd.Timestamp(item.resolution_ts) > REFIT_CUTOFF
                for item in refit_rows
            ):
                raise AssertionError("confirmation refit label crossed 2022 boundary")
            refit_model = base.fit_model(refit_rows)
            base.write_json(
                output / "confirmation_model.json",
                training_model_payload(refit_model, refit_rows, amendment, REFIT_CUTOFF),
            )
            cme_2023, bars_2023, funding_2023, records_2023 = base.core.load_stage(
                session, cache, "confirmation"
            )
            source_records.extend(records_2023)
            opportunities_2023 = build_five_feature_opportunities(cme_2023, bars_2023)
            confirmation_result = base.evaluate_stage(
                "confirmation",
                refit_model,
                opportunities_2023,
                bars_2023,
                funding_2023,
            )
            stage_outputs["confirmation"] = confirmation_result
            confirmation_pass = bool(confirmation_result["stage_pass"])
            base.opportunity_table(opportunities_2023, refit_model).to_csv(
                output / "confirmation_2023_opportunities.csv", index=False
            )
            base.write_json(
                output / "confirmation_result.json",
                {
                    key: value
                    for key, value in confirmation_result.items()
                    if key != "opportunities"
                },
            )

    source_manifest = {
        "schema_version": 1,
        "claim_id": prereg["claim_id"],
        "scientific_contract": amendment["amendment_id"],
        "records": source_records,
        "stages_opened": {
            "training_2021": True,
            "development_2022": True,
            "confirmation_2023": confirmation_opened,
            "official_2024": False,
            "official_2025": False,
            "official_2026": False,
        },
        "orders_submitted": False,
    }
    base.write_json(output / "source_manifest.json", source_manifest)

    summary = {
        "schema_version": 1,
        "claim_id": prereg["claim_id"],
        "result_id": core_amendment["provisional_result_id"],
        "scientific_contract": amendment["amendment_id"],
        "winner_removal_amendment": winner_patch.json.loads(
            winner_patch.WINNER_AMENDMENT_PATH.read_text(encoding="utf-8")
        )["amendment_id"],
        "model_id": MODEL_ID,
        "policy_id": POLICY_ID,
        "policy_count": 1,
        "feature_count": 5,
        "feature_names": list(FIVE_FEATURE_NAMES),
        "model_type": "shared_standardized_l2_logistic_competing_risk",
        "trader_explanation": core_amendment["trader_explanation"],
        "training_opened": True,
        "training_labeled_count": len(training_rows),
        "training_pnl_computed": False,
        "development_opened": True,
        "development_pass": development_pass,
        "confirmation_opened": confirmation_opened,
        "confirmation_pass": confirmation_pass,
        "stage_results": {
            key: {
                name: value
                for name, value in result.items()
                if name not in {"opportunities", "trades", "decisions"}
            }
            for key, result in stage_outputs.items()
        },
        "qualification": "FATAL_PROXY_ML_SCREEN_NOT_RANK_ELIGIBLE",
        "hard_validity_status": "PRELIMINARY_CAUSAL_FIVE_FEATURE_ML_PROXY",
        "official_periods_opened": {"2024": False, "2025": False, "2026": False},
        "orders_submitted": False,
        "paper_or_testnet_started": False,
        "ranking_eligible": False,
        "legacy_432_rule_grid_executed": False,
    }
    base.write_json(output / "result_summary.json", summary)
    print(
        "CME_GAP_FIVE_FEATURE_ML_RESULT="
        + json.dumps(
            {
                "training_labeled_count": len(training_rows),
                "development_pass": development_pass,
                "confirmation_opened": confirmation_opened,
                "confirmation_pass": confirmation_pass,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return summary


def self_test() -> None:
    base.self_test()
    assert len(FIVE_FEATURE_NAMES) == 5
    assert len(FIVE_FEATURE_INDEX) == 5
    assert tuple(ORIGINAL_FEATURE_NAMES[index] for index in FIVE_FEATURE_INDEX) == FIVE_FEATURE_NAMES
    cutoff = pd.Timestamp("2021-12-31T23:59:59Z")
    before = cutoff - pd.Timedelta(hours=1)
    after = cutoff + pd.Timedelta(hours=1)
    allowed = base.Opportunity(
        symbol="BTCUSDT",
        gap_kind="NDOG",
        trading_date="2021-12-31",
        event_open_ts=before,
        entry_ts=before,
        direction=1,
        entry_price=100.0,
        rebalance_level=99.0,
        continuation_level=102.0,
        feature_values=tuple(0.0 for _ in ORIGINAL_FEATURE_NAMES),
        continuation_label=1,
        resolution="continuation_first",
        resolution_ts=before,
    )
    leaked = replace(allowed, resolution_ts=after)
    assert resolved_by(allowed, cutoff) is True
    assert resolved_by(leaked, cutoff) is False
    projected = replace(
        allowed,
        feature_values=tuple(allowed.feature_values[index] for index in FIVE_FEATURE_INDEX),
    )
    assert len(projected.feature_values) == 5
    assert POLICY_ID == hashlib.sha256(MODEL_ID.encode()).hexdigest()[:20]
    sample = winner_patch.np.asarray([100.0, 50.0, -20.0, -10.0])
    corrected = winner_patch.top_positive_removed_return(sample)
    assert isinstance(corrected, float)
    print("FIVE_FEATURE_ANNUAL_OOS_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        run(args.output, args.cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
