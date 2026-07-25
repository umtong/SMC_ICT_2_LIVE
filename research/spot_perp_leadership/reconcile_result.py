from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
UPDATED_AT = "2026-07-26T01:18:05+09:00"
RESULT_ID = "RES-20260726-SPOT-PERP-LEADERSHIP-001"
DVOL_RESULT_ID = "RES-20260726-DVOL-XSEC-001"
CLAIM_ID = "CLM-20260726-0017-SPOTPERP-TAKEOVER-001"
SOURCE_ID = "SRC-BINANCE-PUBLIC-SPOT-USDM-1M-20260726"
DATASET_ID = "DS-BINANCE-SPOT-USDM-BTCETH-1M-202110-202212-R1"
ATTESTATION_ID = "VAL-20260726-SPOT-PERP-LEADERSHIP-001"
RUN_REPORT_URL = "https://docs.google.com/document/d/1j78Ih8g2rHCmE-BTPjNb8phrUa_krhcWY5RYv0trn-Q/edit"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def compact(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(compact(row) for row in records) + "\n", encoding="utf-8")


def append_unique(records: list[dict[str, Any]], key: str, value: dict[str, Any]) -> None:
    existing = [row for row in records if row.get(key) == value.get(key)]
    if not existing:
        records.append(value)
        return
    if existing[0] != value:
        raise AssertionError(f"conflicting {key}={value.get(key)}")


def registry_result(report: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "schema_version",
        "result_id",
        "claim_id",
        "worker_id",
        "status",
        "hard_validity_status",
        "economic_status",
        "summary",
        "source_ids",
        "dataset_ids",
        "code_commit",
        "evaluation_contract_sha256",
        "artifact_fingerprint",
        "dependency_fingerprint",
        "artifact_links",
        "created_at",
    )
    return {key: report[key] for key in keys}


def registry_validation(attestation: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "attestation_id",
        "dependency_fingerprint",
        "validation_scope",
        "changed_surface",
        "status",
        "evidence",
        "created_at",
    )
    return {key: attestation[key] for key in keys}


def reconcile_registries() -> None:
    source_path = ROOT / "data/catalog/source-registry.jsonl"
    sources = read_jsonl(source_path)
    append_unique(
        sources,
        "source_id",
        {
            "schema_version": 1,
            "source_id": SOURCE_ID,
            "source_type": "exchange_public_archive",
            "title": "Binance Public Spot and USD-M Monthly Archives",
            "provider": "Binance",
            "canonical_url": "https://data.binance.vision/",
            "retrieved_at": UPDATED_AT,
            "status": "VERIFIED_RESEARCH_USED",
            "language": "en",
            "sha256": "e5fb549b83795744f32b0121486b4ea0337e2113e2732dcf39cdcd249089d6a5",
            "notes": (
                "Checksum-verified BTCUSDT and ETHUSDT spot klines, USD-M perpetual klines, "
                "mark-price klines and funding-rate archives for 2021-10 through 2022-12. "
                "Bars are usable only after close and funding only at official calc_time."
            ),
            "tags": ["binance", "spot", "usdm", "klines", "funding", "official_archive"],
        },
    )
    write_jsonl(source_path, sources)

    dataset_path = ROOT / "data/catalog/dataset-registry.jsonl"
    datasets = read_jsonl(dataset_path)
    append_unique(
        datasets,
        "dataset_id",
        {
            "schema_version": 1,
            "dataset_id": DATASET_ID,
            "provider": "Binance public data",
            "market": "BTCUSDT and ETHUSDT spot plus USD-M perpetual futures",
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "timeframe": "one-minute spot, USD-M contract and mark-price bars plus exact funding events",
            "start": "2021-10-01T00:00:00Z",
            "end": "2022-12-31T23:59:59Z",
            "snapshot_at": UPDATED_AT,
            "status": "VERIFIED_RESEARCH_ONLY",
            "canonical_url": "https://data.binance.vision/",
            "sha256": "40b04012204a7079b53a8521bd7694c22e530bfbfdab65971955ad2d9bd32795",
            "component_sha256": {
                "source_manifest": "e5fb549b83795744f32b0121486b4ea0337e2113e2732dcf39cdcd249089d6a5",
                "gap_audit": "0f885fda67c35bca94253612135ea14c4d4613d03ab1adf4589cdd3400ca3faf",
                "artifact_archive": "2d72befe8398bf8bf960453e4378a69a1c90ae4dcd516b20f5294299806f1768",
            },
            "size_bytes": 154574732,
            "license_or_terms": "Binance public data terms apply",
            "causal_availability": (
                "One-minute bars become usable only after close; funding is usable only at calc_time. "
                "Regular UTC gaps remain NaN with no filling, interpolation or timeline compression."
            ),
            "notes": (
                "120 adjacent-CHECKSUM-verified monthly archives. The 658080-minute regular grid has "
                "2891 minutes with at least one absent source stream; spot and USD-M contract bars "
                "are complete, while mark gaps remain explicit. 2023 and later were never acquired."
            ),
        },
    )
    write_jsonl(dataset_path, datasets)

    entity_path = ROOT / "data/catalog/entity-registry.jsonl"
    entities = read_jsonl(entity_path)
    append_unique(
        entities,
        "entity_id",
        {
            "schema_version": 1,
            "entity_id": "exchange:binance-spot",
            "entity_type": "exchange_market",
            "name": "Binance Spot",
            "aliases": ["Binance Spot Market"],
            "languages": ["en"],
            "canonical_url": "https://developers.binance.com/docs/binance-spot-api-docs",
            "status": "REGISTERED_RESEARCH_USED",
            "source_ids": [SOURCE_ID],
            "last_checked_at": UPDATED_AT,
            "notes": "Official spot-market leg used with Binance USD-M for causal price-discovery research.",
        },
    )
    write_jsonl(entity_path, entities)

    report = read_json(ROOT / "research/reports" / f"{RESULT_ID}.json")
    dvol_report = read_json(ROOT / "research/reports" / f"{DVOL_RESULT_ID}.json")
    result_path = ROOT / "control/result-registry.jsonl"
    result_records = read_jsonl(result_path)
    append_unique(result_records, "result_id", registry_result(dvol_report))
    append_unique(result_records, "result_id", registry_result(report))
    write_jsonl(result_path, result_records)

    attestation = read_json(ROOT / "runs/validation-cache" / f"{ATTESTATION_ID}.json")
    dvol_attestation = read_json(ROOT / "runs/validation-cache/VAL-20260726-DVOL-XSEC-001.json")
    validation_path = ROOT / "control/validation-cache.jsonl"
    validation_records = read_jsonl(validation_path)
    append_unique(validation_records, "attestation_id", registry_validation(dvol_attestation))
    append_unique(validation_records, "attestation_id", registry_validation(attestation))
    write_jsonl(validation_path, validation_records)


def reconcile_work_claims() -> None:
    path = ROOT / "control/work-claims.csv"
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    if not any(row["claim_id"] == CLAIM_ID for row in rows):
        rows.append(
            {
                "claim_id": CLAIM_ID,
                "worker_id": "gpt-5.6-pro-20260726-0017",
                "objective_fingerprint": "7615ea09f5bc30d2edffdbb44c1a611ba46668022ded19cf9d98acd69d78da32",
                "scope_fingerprint": "1bf967f19d2e6123996d16c63d5896b4320c45a8ffcb07fdb142f754bd0979ff",
                "base_revision": "8",
                "status": "REPORTED",
                "started_at": "2026-07-26T00:17:23+09:00",
                "lease_until": "2026-07-26T08:17:23+09:00",
                "branch": "agent/r8-spot-perp-leadership-001",
                "pull_request": "https://github.com/umtong/SMC_ICT_2_LIVE/pull/43",
                "result_id": RESULT_ID,
                "overlap_reason": (
                    "Continuation of an expired no-output claim. Official spot/USD-M price-discovery "
                    "scope excluded active flow-size, L2, cross-venue, positioning, COIN-M and DVOL work; "
                    "all four completed-bar families are now exhausted under this dependency fingerprint."
                ),
                "updated_at": UPDATED_AT,
            }
        )
    fieldnames = [
        "claim_id",
        "worker_id",
        "objective_fingerprint",
        "scope_fingerprint",
        "base_revision",
        "status",
        "started_at",
        "lease_until",
        "branch",
        "pull_request",
        "result_id",
        "overlap_reason",
        "updated_at",
    ]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(out.getvalue(), encoding="utf-8")


def reconcile_ranking() -> None:
    path = ROOT / "control/ranking.json"
    ranking = read_json(path)
    if ranking.get("revision") != 9:
        if any(row.get("source_result_id") == RESULT_ID for row in ranking.get("ranked_candidates", [])):
            return
        raise AssertionError(
            f"Expected ranking revision 9 before insertion, found {ranking.get('revision')}; re-evaluate latest state."
        )

    existing = {row["source_result_id"]: row for row in ranking["ranked_candidates"]}
    required = [
        "RES-20260725-DYNAMIC-FACTOR-001",
        "RES-20260725-ABS-FLOW-001",
        "RES-20260725-ALPHA-HYP-001",
        "RES-20260725-CAUSAL-ALPHA-WAVE1-001",
        "RES-20260725-CROSS-ASSET-LEADLAG-001",
    ]
    missing = [item for item in required if item not in existing]
    if missing:
        raise AssertionError(f"ranking revision 9 missing expected records: {missing}")

    ordered = [
        existing["RES-20260725-DYNAMIC-FACTOR-001"],
        existing["RES-20260725-ABS-FLOW-001"],
        {
            "source_result_id": RESULT_ID,
            "candidate_label": "perp_overshoot_reversal 191444bb0a4348e2a52b",
            "geometric_daily_growth": 0.0001189762570252828,
            "target_gap": 0.009881023742974717,
            "comparison_confidence": "LOW",
            "comparison_status": "PROVISIONAL_DIFFERENT_WINDOW_MARKET_AND_EXECUTION_CONTRACT",
        },
        {
            "source_result_id": DVOL_RESULT_ID,
            "candidate_label": "LOW_VRP_RESIDUAL_CONTINUATION 1b4ec83c59bb98660c23",
            "geometric_daily_growth": 0.00003400166161160456,
            "target_gap": 0.009965998338388396,
            "comparison_confidence": "LOW",
            "comparison_status": "PROVISIONAL_DIFFERENT_WINDOW_MARKET_AND_EXECUTION_CONTRACT",
        },
        existing["RES-20260725-ALPHA-HYP-001"],
        existing["RES-20260725-CAUSAL-ALPHA-WAVE1-001"],
        existing["RES-20260725-CROSS-ASSET-LEADLAG-001"],
    ]
    for rank, row in enumerate(ordered, start=1):
        row["rank"] = rank

    ranking["revision"] = 10
    ranking["ranking_id"] = "STRATEGY-RANKING-20260726-R10"
    ranking["ranked_candidates"] = ordered
    ranking["updated_at"] = UPDATED_AT
    ranking["reconciliation_notes"] = [
        "Inserted hard-valid RES-20260726-SPOT-PERP-LEADERSHIP-001 at provisional rank 3 by after-cost daily-growth target proximity.",
        "Inserted previously merged but omitted RES-20260726-DVOL-XSEC-001 at provisional rank 4.",
        "First place and its qualification, economic failure and deployability status are unchanged."
    ]
    write_json(path, ranking)


def reconcile_current_state() -> None:
    path = ROOT / "control/current-state.md"
    text = path.read_text(encoding="utf-8")
    if "- revision: 10" in text and RESULT_ID in text:
        return
    if "- revision: 9" not in text:
        raise AssertionError("Expected current-state revision 9 before reconciliation")
    path.write_text(
        """# Current state

- revision: 10
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260725-DYNAMIC-STATE-021FBAB6`
- first-place stage: `EXPLORATORY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`
- Drive root: resolved privately through `config/project.local.toml` or `00_PROJECT_BINDING`

## Current strategy ranking

The current first place is dynamic state-exit candidate `021fbab613517a31ad98` from `RES-20260725-DYNAMIC-FACTOR-001` / PR #25.

- 12 bps and actual-funding geometric daily growth: `0.0573077%`
- 1% target gap: `0.9426923 percentage points per trading day`
- target fraction: `5.73077%`
- total return: `+23.2585%`
- maximum drawdown: `4.6174%`
- trades: `194`
- profit factor: `1.5041`
- top-five positive-trade share: `35.35%`
- return at 18 bps: `+16.7170%`
- return at 24 bps: `+11.2649%`

It remains first because it has the smallest verified recorded after-cost daily-growth gap among hard-valid results. The rank is provisional: the registered economic gate failed, top-10%-removed return is `-21.8583%`, median per-trade return is negative, all four portfolios frozen from 2023 lost in 2024, and the exact candidate has no opened 2024 out-of-sample interval.

The current second place is `aligned_continuation 33034b092ffd271a` from `RES-20260725-ABS-FLOW-001` / PR #35.

- approximately 15 bps round-trip geometric daily growth: `0.0227977%`
- target gap: `0.9772023 percentage points per trading day`
- total return: `+15.6276%`
- maximum drawdown: `6.4718%`
- trades: `184`
- profit factor: `1.3065`
- top-five positive-trade share: `18.00%`
- approximately 30 bps geometric daily growth: `0.0118956%`

It is hard-valid but failed the preregistered yearly robustness gate. No sequential 2024 or 2025H1 interval was opened, and the approximately 30 bps path becomes negative after removing the top five winners.

The provisional third place is `perp_overshoot_reversal 191444bb0a4348e2a52b` from `RES-20260726-SPOT-PERP-LEADERSHIP-001` / PR #43.

- 12 bps geometric daily growth: `0.0118976%`
- target gap: `0.9881024 percentage points per trading day`
- total return: `+4.4380%`
- maximum drawdown: `1.2337%`
- trades: `17`
- profit factor: `2.4637`
- top-five positive-trade share: `92.76%`
- top-10%-removed return: `-0.5817%`
- 18/24 bps geometric daily growth: `0.0094770%` / `0.0070550%`

It is hard-valid but failed five development gates, including sample count, positive median trade and top-trade-removal robustness. Zero of 496 candidates survived; 2023 and later remained unopened. Its rank reflects target proximity only, with low comparison confidence.

The provisional fourth place is the raw DVOL-conditioned residual candidate `1b4ec83c59bb98660c23` from `RES-20260726-DVOL-XSEC-001`.

- 12 bps geometric daily growth: `0.0034002%`
- target gap: `0.9965998 percentage points per trading day`
- total return: `+0.9291%`
- maximum drawdown: `3.4484%`
- trades: `76`
- profit factor: `1.0684`
- top-10%-removed return: `-7.3742%`

It lost at 18 and 24 bps, had a negative median trade and produced zero development survivors. The former `high_resistance_sweep c232ae43b7a1401d` is rank 5.

The current execution-routing component first place remains `RES-20260725-1510-L1-EXEC-001`, which improved modeled execution drag but has negative standalone expectancy.

## Ranking policy

- Hard-invalid results are excluded from strategy ranking but remain in the failure record.
- The primary ranking criterion is closeness to the full project objective, led by the gap to 1% after-cost geometric daily growth.
- A forced-liquidation or irrecoverable account path cannot outrank a survival-qualified candidate solely through raw return.
- Drawdown/recovery, liquidation/tail risk, concentration, effective independent trades, execution robustness, capital efficiency and comparison confidence resolve similar or uncertain target gaps.
- Economic gate failure, validation stage and deployability are reported separately from rank.
- Rank does not determine research priority, validation budget, protection or the next work item.
- Results are recorded once; rank changes update the ranking record without repeated backup or validation.

## Active work

Material active claims include the fixed raw-event two-strategy portfolio, flow-size/impact-efficiency state research, L2 maker toxicity, cross-venue forward capture/recovery, multi-asset positioning states and COIN-M collateral-stress transmission. Spot/perpetual one-minute completed-bar leadership is now reported and should not receive adjacent-threshold tuning under the recorded dependency fingerprint.

Reported work has rejected causal alpha wave 1, exact funding-settlement families, completed-bar fixed lead-lag, fixed BTC OI-shock families, transcript-derived five-minute formulations, liquidity-sweep engulfing first-touch variants, ordinary five-minute absorption, prior-volume dollar-clock absorption and completed-bar spot/perpetual price-discovery thresholds under their tested dependencies.

## Current objective

Finish and reuse decision-ready outputs from active claims, including the fixed account-level portfolio replay. If none materially closes the target gap, open a non-overlapping information-source claim rather than retuning reported families. Favor sub-minute liquidation replenishment/order-book resiliency or another structurally different payoff source after checking current cross-venue and L2 scopes.

## Current blockers

The first four ranks remain far below the 1% target and all have material concentration, robustness or cost defects. No candidate has survived sequential selection with robust cost, concentration and regime behavior. Capital velocity remains low, and historical queue/depth execution is incomplete.

## Next exact action

Consume decision-ready fixed-portfolio, flow-size, L2 maker, cross-venue, positioning and COIN-M outputs as they finish. Do not retune dynamic-factor, ordinary absorption, DVOL or completed-bar spot/perpetual dependencies. If active outputs remain below target, claim the highest-value non-overlapping sub-minute information source.
""",
        encoding="utf-8",
    )


def reconcile_claim_and_pointers() -> None:
    claim_path = ROOT / "research/spot_perp_leadership/WORK_CLAIM.json"
    claim = read_json(claim_path)
    claim.update(
        {
            "status": "REPORTED",
            "result_id": RESULT_ID,
            "reported_at": UPDATED_AT,
            "final_project_revision": 10,
            "run_report_url": RUN_REPORT_URL,
            "artifact_id": 8621251086,
            "artifact_sha256": "2d72befe8398bf8bf960453e4378a69a1c90ae4dcd516b20f5294299806f1768",
        }
    )
    write_json(claim_path, claim)
    write_json(
        ROOT / "research/spot_perp_leadership/RESULT_POINTER.json",
        {
            "schema_version": 1,
            "result_id": RESULT_ID,
            "report_path": f"research/reports/{RESULT_ID}.json",
            "validation_path": f"runs/validation-cache/{ATTESTATION_ID}.json",
            "run_report_url": RUN_REPORT_URL,
            "github_actions_run": 30164791274,
            "github_actions_artifact_id": 8621251086,
            "artifact_sha256": "2d72befe8398bf8bf960453e4378a69a1c90ae4dcd516b20f5294299806f1768",
            "status": "TESTED_BELOW_GATE",
            "hard_validity_status": "PASS",
            "economic_status": "BELOW_GATE",
            "ranking_role": "PROVISIONAL_RANK_3",
            "updated_at": UPDATED_AT,
        },
    )


def main() -> int:
    reconcile_registries()
    reconcile_work_claims()
    reconcile_ranking()
    reconcile_current_state()
    reconcile_claim_and_pointers()
    print(
        compact(
            {
                "result_id": RESULT_ID,
                "project_revision": 10,
                "ranking_role": "PROVISIONAL_RANK_3",
                "dvol_reconciled_rank": 4,
                "status": "REPORTED",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
