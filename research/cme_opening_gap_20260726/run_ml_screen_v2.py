from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

import run_ml_screen as base

PURGE_AMENDMENT_PATH = Path(__file__).resolve().parent / "amendment_002_purged_training_cutoff.json"


def resolved_by(item: base.Opportunity, cutoff: pd.Timestamp) -> bool:
    return (
        item.continuation_label in (0, 1)
        and item.resolution_ts is not None
        and pd.Timestamp(item.resolution_ts) <= cutoff
    )


def run(output: Path, cache: Path) -> dict[str, Any]:
    prereg = json.loads(base.PREREG_PATH.read_text(encoding="utf-8"))
    amendment = json.loads(base.AMENDMENT_PATH.read_text(encoding="utf-8"))
    purge = json.loads(PURGE_AMENDMENT_PATH.read_text(encoding="utf-8"))
    if amendment["claim_id"] != prereg["claim_id"] or purge["claim_id"] != prereg["claim_id"]:
        raise ValueError("ML amendment claim mismatch")
    if purge["parent_amendment_id"] != amendment["amendment_id"]:
        raise ValueError("purge amendment parent mismatch")
    if amendment["active_model_contract"]["policy_count"] != 1:
        raise ValueError("ML core must contain exactly one policy")
    output.mkdir(parents=True, exist_ok=True)

    all_source_records: list[dict[str, Any]] = []
    stage_outputs: dict[str, Any] = {}
    with base.core.requests.Session() as session:
        session.headers["User-Agent"] = "SMC-ICT-2-LIVE-CME-gap-ML-purged/1.0"
        cme_2021, bars_2021, funding_2021, records_2021 = base.core.load_stage(
            session, cache, "fit"
        )
        all_source_records.extend(records_2021)
        opportunities_2021 = base.build_opportunities(cme_2021, bars_2021)

        entered_before_cutoff = [
            item for item in opportunities_2021
            if item.entry_ts <= base.TRAIN_END
        ]
        train_rows = [
            item for item in entered_before_cutoff
            if resolved_by(item, base.TRAIN_END)
        ]
        purged_cross_boundary = [
            item for item in entered_before_cutoff
            if item.continuation_label in (0, 1)
            and item.resolution_ts is not None
            and pd.Timestamp(item.resolution_ts) > base.TRAIN_END
        ]
        fit_rows = [
            item for item in opportunities_2021
            if item.entry_ts >= base.FIT_HOLDOUT_START
        ]
        if any(
            item.resolution_ts is None or pd.Timestamp(item.resolution_ts) > base.TRAIN_END
            for item in train_rows
        ):
            raise AssertionError("training label crossed the fit-holdout boundary")

        model = base.fit_model(train_rows)
        fit_result = base.evaluate_stage(
            "fit_holdout", model, fit_rows, bars_2021, funding_2021
        )
        stage_outputs["fit_holdout"] = fit_result
        base.opportunity_table(train_rows, model).to_csv(
            output / "train_2021_opportunities.csv", index=False
        )
        base.opportunity_table(fit_rows, model).to_csv(
            output / "fit_holdout_2021_opportunities.csv", index=False
        )
        model_payload = base.serialize_model(model, train_rows)
        model_payload.update({
            "purge_amendment_id": purge["amendment_id"],
            "entered_before_training_cutoff_count": len(entered_before_cutoff),
            "purged_cross_boundary_label_count": len(purged_cross_boundary),
            "training_max_entry_ts": max(str(item.entry_ts) for item in train_rows),
            "training_max_resolution_ts": max(str(item.resolution_ts) for item in train_rows),
            "training_label_resolution_cutoff": str(base.TRAIN_END),
        })
        base.write_json(output / "fit_model.json", model_payload)
        base.write_json(
            output / "fit_holdout_result.json",
            {key: value for key, value in fit_result.items() if key != "opportunities"},
        )

        development_opened = bool(fit_result["stage_pass"])
        development_pass = False
        confirmation_opened = False
        confirmation_pass = False
        opportunities_2022: list[base.Opportunity] = []
        if development_opened:
            cme_2022, bars_2022, funding_2022, records_2022 = base.core.load_stage(
                session, cache, "development"
            )
            all_source_records.extend(records_2022)
            opportunities_2022 = base.build_opportunities(cme_2022, bars_2022)
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
            if confirmation_opened:
                refit_cutoff = pd.Timestamp("2022-12-31T23:59:59Z")
                refit_rows = [
                    item for item in opportunities_2021 + opportunities_2022
                    if resolved_by(item, refit_cutoff)
                ]
                refit_model = base.fit_model(refit_rows)
                confirmation_model = base.serialize_model(refit_model, refit_rows)
                confirmation_model.update({
                    "purge_amendment_id": purge["amendment_id"],
                    "training_label_resolution_cutoff": str(refit_cutoff),
                    "training_max_resolution_ts": max(
                        str(item.resolution_ts) for item in refit_rows
                    ),
                })
                base.write_json(
                    output / "confirmation_model.json", confirmation_model
                )
                cme_2023, bars_2023, funding_2023, records_2023 = base.core.load_stage(
                    session, cache, "confirmation"
                )
                all_source_records.extend(records_2023)
                opportunities_2023 = base.build_opportunities(cme_2023, bars_2023)
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
        "purge_amendment": purge["amendment_id"],
        "records": all_source_records,
        "stages_opened": {
            "fit_2021": True,
            "development_2022": development_opened,
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
        "result_id": amendment["provisional_result_id"],
        "scientific_contract": amendment["amendment_id"],
        "purge_amendment": purge["amendment_id"],
        "model_id": base.MODEL_ID,
        "policy_count": 1,
        "model_type": "shared_standardized_l2_logistic_competing_risk",
        "trader_explanation": amendment["trader_explanation"],
        "fit_pass": bool(stage_outputs["fit_holdout"]["stage_pass"]),
        "development_opened": development_opened,
        "development_pass": development_pass,
        "confirmation_opened": confirmation_opened,
        "confirmation_pass": confirmation_pass,
        "training_entered_before_cutoff_count": len(entered_before_cutoff),
        "training_labeled_count": len(train_rows),
        "purged_cross_boundary_label_count": len(purged_cross_boundary),
        "stage_results": {
            key: {
                name: value
                for name, value in result.items()
                if name not in {"opportunities", "trades", "decisions"}
            }
            for key, result in stage_outputs.items()
        },
        "qualification": "FATAL_PROXY_ML_SCREEN_NOT_RANK_ELIGIBLE",
        "hard_validity_status": "PRELIMINARY_CAUSAL_ML_PROXY_PURGED",
        "official_periods_opened": {"2024": False, "2025": False, "2026": False},
        "orders_submitted": False,
        "paper_or_testnet_started": False,
        "ranking_eligible": False,
        "legacy_432_rule_grid_executed": False,
    }
    base.write_json(output / "result_summary.json", summary)
    print(
        "CME_GAP_ML_RESULT="
        + json.dumps(
            {
                "fit_pass": summary["fit_pass"],
                "development_opened": development_opened,
                "development_pass": development_pass,
                "confirmation_opened": confirmation_opened,
                "confirmation_pass": confirmation_pass,
                "training_labeled_count": len(train_rows),
                "purged_cross_boundary_label_count": len(purged_cross_boundary),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return summary


def self_test() -> None:
    base.self_test()
    cutoff = pd.Timestamp("2021-08-31T23:59:59Z")
    before = cutoff - pd.Timedelta(hours=1)
    after = cutoff + pd.Timedelta(hours=1)
    allowed = base.Opportunity(
        symbol="BTCUSDT",
        gap_kind="NDOG",
        trading_date="2021-08-31",
        event_open_ts=before,
        entry_ts=before,
        direction=1,
        entry_price=100.0,
        rebalance_level=99.0,
        continuation_level=102.0,
        feature_values=tuple(0.0 for _ in base.FEATURE_NAMES),
        continuation_label=1,
        resolution="continuation_first",
        resolution_ts=before,
    )
    leaked = base.Opportunity(
        symbol="BTCUSDT",
        gap_kind="NDOG",
        trading_date="2021-08-31",
        event_open_ts=before,
        entry_ts=before,
        direction=1,
        entry_price=100.0,
        rebalance_level=99.0,
        continuation_level=102.0,
        feature_values=tuple(0.0 for _ in base.FEATURE_NAMES),
        continuation_label=1,
        resolution="continuation_first",
        resolution_ts=after,
    )
    assert resolved_by(allowed, cutoff) is True
    assert resolved_by(leaked, cutoff) is False
    print("PURGED_TRAINING_SELF_TEST_PASS")


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
