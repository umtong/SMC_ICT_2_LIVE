from __future__ import annotations

import collections
import datetime as dt
import gzip
import json
from pathlib import Path
from typing import Any, Iterable

import source_gate_coinm as base

CLAIM_ID = base.CLAIM_ID
MARKET_SCOPE = base.MARKET_SCOPE
SOURCE_SYMBOLS = base.SOURCE_SYMBOLS
BYBIT_SIGNAL_MAP = base.BYBIT_SIGNAL_MAP
START_DATE = base.START_DATE
END_DATE = base.END_DATE
FIXED_SAMPLE_DATES = base.FIXED_SAMPLE_DATES
EXPECTED_FIELDS = base.EXPECTED_FIELDS
SourceGateError = base.SourceGateError

SNAPSHOT_SEMANTICS = {
    "publication": "latest one liquidation order per symbol per 1000ms interval",
    "coverage": "censored lower-bound observation of forced activity, not a complete liquidation ledger",
    "absence": "no published row does not prove no liquidation occurred",
    "quantity": "published executed contract count; never original unfilled order quantity",
    "notional": "executed contract count multiplied by separately hash-recorded COIN-M contractSize",
}

# Preserve the immutable pre-correction parser for transparent transport reuse.
_ORIGINAL_ITER_LIQUIDATION_ROWS = base.iter_liquidation_rows


def executed_contract_count(row: dict[str, Any]) -> float:
    accumulated = float(row["accumulated_filled_quantity"])
    last = float(row["last_filled_quantity"])
    if accumulated > 0:
        return accumulated
    if last > 0:
        return last
    return 0.0


def iter_published_executed_rows(payload: bytes) -> Iterable[dict[str, Any]]:
    """Yield only published snapshots with observed positive executed quantity.

    The parent parser is reused for schema, timestamp, side and numeric validation.  This
    correction deliberately removes its original-quantity fallback: an unfilled forced
    order is source diagnostics, not executed liquidation flow.
    """

    for parsed in _ORIGINAL_ITER_LIQUIDATION_ROWS(payload):
        executed = executed_contract_count(parsed)
        if executed <= 0:
            continue
        yield {
            **parsed,
            "effective_quantity": executed,
            "published_executed_contract_count": executed,
            "has_executed_fill": True,
            "snapshot_is_complete_liquidation_ledger": False,
        }


def inspect_archive(
    session: Any,
    *,
    key: str,
    symbol: str,
    expected_date: str,
    sample_output: gzip.GzipFile,
) -> dict[str, Any]:
    filename = Path(key).name
    checksum_url = f"{base.DOWNLOAD_BASE}/{key}.CHECKSUM"
    archive_url = f"{base.DOWNLOAD_BASE}/{key}"
    checksum_payload = base.request_bytes(session, checksum_url)
    expected_digest = base.parse_checksum(checksum_payload, filename)
    archive_payload = base.request_bytes(session, archive_url)
    observed_digest = base.sha256_bytes(archive_payload)
    if observed_digest != expected_digest:
        raise SourceGateError(f"checksum mismatch for {filename}")

    start = dt.datetime.fromisoformat(expected_date).replace(tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    status_counts: collections.Counter[str] = collections.Counter()
    raw_row_count = 0
    zero_executed_row_count = 0
    rows: list[dict[str, Any]] = []

    for parsed in _ORIGINAL_ITER_LIQUIDATION_ROWS(archive_payload):
        raw_row_count += 1
        status_counts[str(parsed["order_status"])] += 1
        observed = dt.datetime.fromtimestamp(parsed["time"] / 1000, tz=dt.timezone.utc)
        if not (start <= observed < end):
            raise SourceGateError(
                f"{filename} row outside {expected_date}: {observed.isoformat()}"
            )
        executed = executed_contract_count(parsed)
        if executed <= 0:
            zero_executed_row_count += 1
            continue
        enriched = {
            **parsed,
            "effective_quantity": executed,
            "published_executed_contract_count": executed,
            "has_executed_fill": True,
            "snapshot_is_complete_liquidation_ledger": False,
            "source_symbol": symbol,
            "bybit_symbol": BYBIT_SIGNAL_MAP[symbol],
            "source_key": key,
            "source_date": expected_date,
        }
        sample_output.write((base.stable_json(enriched) + "\n").encode("utf-8"))
        rows.append(enriched)

    identities = {
        (
            row["time"],
            row["side"],
            round(float(row["effective_price"]), 12),
            round(float(row["effective_quantity"]), 12),
        )
        for row in rows
    }
    return {
        "key": key,
        "filename": filename,
        "date": expected_date,
        "symbol": symbol,
        "archive_bytes": len(archive_payload),
        "archive_sha256": observed_digest,
        "checksum_sha256": base.sha256_bytes(checksum_payload),
        "raw_row_count": raw_row_count,
        "row_count": len(rows),
        "positive_executed_row_count": len(rows),
        "zero_executed_row_count": zero_executed_row_count,
        "order_status_counts": dict(sorted(status_counts.items())),
        "unique_identity_count": len(identities),
        "sides": sorted({row["side"] for row in rows}),
        "snapshot_semantics": SNAPSHOT_SEMANTICS,
    }


def run(output: Path) -> dict[str, Any]:
    # The parent run resolves inspect_archive from its module globals at runtime.
    original_inspect = base.inspect_archive
    base.inspect_archive = inspect_archive
    try:
        result = base.run(output)
    finally:
        base.inspect_archive = original_inspect

    manifest_path = output / "SOURCE_MANIFEST.json"
    result_path = output / "SOURCE_GATE_RESULT.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    sample_archives = manifest.get("sample_archives", [])
    raw_rows = sum(int(row.get("raw_row_count", row.get("row_count", 0))) for row in sample_archives)
    executed_rows = sum(int(row.get("positive_executed_row_count", row.get("row_count", 0))) for row in sample_archives)
    zero_rows = sum(int(row.get("zero_executed_row_count", 0)) for row in sample_archives)
    statuses: collections.Counter[str] = collections.Counter()
    for row in sample_archives:
        statuses.update({str(k): int(v) for k, v in row.get("order_status_counts", {}).items()})

    manifest.update(
        {
            "source_semantics": SNAPSHOT_SEMANTICS,
            "authoritative_corrections": [
                "CORRECTION-20260726-ML-BINANCE-LIQ-COINM-CONTRACT-NOTIONAL-003",
                "CORRECTION-20260726-ML-BINANCE-LIQ-SNAPSHOT-CENSORING-EXECUTED-FILL-004",
            ],
            "sample_diagnostics": {
                "raw_published_snapshot_rows": raw_rows,
                "positive_executed_snapshot_rows": executed_rows,
                "zero_executed_snapshot_rows_excluded": zero_rows,
                "order_status_counts": dict(sorted(statuses.items())),
            },
        }
    )

    checks = dict(result.get("checks", {}))
    checks.update(
        {
            "snapshot_censoring_disclosed": True,
            "original_quantity_fallback_prohibited": True,
            "only_positive_executed_snapshots_enter_signal_rows": executed_rows == int(result.get("totals", {}).get("sample_row_count", executed_rows)),
            "contract_count_semantics_bound": True,
        }
    )
    result["checks"] = checks
    result["source_semantics"] = SNAPSHOT_SEMANTICS
    result["authoritative_corrections"] = manifest["authoritative_corrections"]
    result.setdefault("totals", {}).update(manifest["sample_diagnostics"])

    if result.get("status") == "PASS" and not all(checks.values()):
        result["status"] = "BELOW_SOURCE_GATE"
        result["source_gate_pass"] = False
        result["scientific_decision"] = "CLOSE_OFFICIAL_LIQUIDATION_SNAPSHOT_ROUTE_BEFORE_OUTCOMES"

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> None:
    base.self_test()
    assert SNAPSHOT_SEMANTICS["coverage"].startswith("censored lower-bound")
    assert executed_contract_count(
        {"accumulated_filled_quantity": 3.0, "last_filled_quantity": 1.0}
    ) == 3.0
    assert executed_contract_count(
        {"accumulated_filled_quantity": 0.0, "last_filled_quantity": 2.0}
    ) == 2.0
    assert executed_contract_count(
        {"accumulated_filled_quantity": 0.0, "last_filled_quantity": 0.0}
    ) == 0.0
    print("COIN_M_EXECUTED_SNAPSHOT_CORRECTION_SELF_TEST_PASS")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        raise SystemExit("--output is required")
    result = run(args.output)
    print(
        json.dumps(
            {
                "status": result["status"],
                "source_gate_pass": result["source_gate_pass"],
                "scientific_decision": result["scientific_decision"],
                "source_semantics": result["source_semantics"],
                "totals": result.get("totals", {}),
                "fatal_error": result.get("fatal_error"),
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
