from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

import source_gate_v2 as adapted_gate

# source_gate_v2 adapts the parent's frozen tuple windows before importing here.
gate = adapted_gate.gate
nportal = gate.PortalClient
base = gate.base
semantic = gate.semantic

START_UTC = "2021-07-01T00:00:00Z"
END_EXCLUSIVE_UTC = "2024-01-01T00:00:00Z"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_gzip(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="\n") as text:
                for row in rows:
                    text.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def identity(row: dict[str, Any]) -> str:
    return f"{row['block_hash']}|{row['transaction_hash']}|{int(row['log_index'])}"


def semantic_subset(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "block_hash",
            "transaction_hash",
            "log_index",
            "asset",
            "liquidated_position_side",
            "size_raw_1e30",
            "block_timestamp",
            "causal_available_timestamp",
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    authority = json.loads(args.authority.read_text(encoding="utf-8"))
    if not authority.get("source_gate_pass"):
        raise SystemExit("full history requires a passing source authority")
    if authority.get("scientific_decision") != "OPEN_FROZEN_PRE2024_HISTORY_AND_MODEL_STAGE":
        raise SystemExit("source authority did not open pre-2024 history")

    client = portal()
    start_ts = base.parse_utc(START_UTC)
    end_ts = base.parse_utc(END_EXCLUSIVE_UTC)
    from_block = client.resolve_timestamp(start_ts)
    to_block = max(from_block, client.resolve_timestamp(end_ts) - 1)

    rows: list[dict[str, Any]] = []
    decode_errors: list[dict[str, Any]] = []
    raw_logs = 0
    for portal_row in client.stream(from_block=from_block, to_block=to_block):
        header = portal_row["header"]
        for portal_log in portal_row.get("logs", []):
            raw_logs += 1
            try:
                rpc_log, block_timestamp = gate.portal_log_to_rpc(header, portal_log)
                decoded = semantic.decode_liquidation_log(
                    rpc_log,
                    block_timestamp=block_timestamp,
                    probe_window="FULL_PRE2024_HISTORY",
                )
                if decoded["asset"] not in base.INDEX_TOKENS:
                    continue
                decoded.pop("raw_log", None)
                rows.append(decoded)
            except Exception as exc:
                decode_errors.append(
                    {
                        "block": header.get("number"),
                        "transactionHash": portal_log.get("transactionHash"),
                        "logIndex": portal_log.get("logIndex"),
                        "error": repr(exc),
                    }
                )

    rows.sort(
        key=lambda row: (
            int(row["block_timestamp"]),
            int(row["transaction_index"]),
            int(row["log_index"]),
        )
    )
    ids = [identity(row) for row in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate full-history identities")
    if decode_errors:
        raise SystemExit(f"decode errors: {decode_errors[:5]}")
    for row in rows:
        if (
            row.get("external_market_order_direction_asserted") is not False
            or row.get("source_censoring") != "LIQUIDATION_STATE_1_ONLY"
            or "forced_flow_direction" in row
        ):
            raise SystemExit("semantic correction failed in full history")

    # The full history must reproduce the frozen six-window authority exactly.
    probe_counts: dict[str, int] = {}
    probe_ids: list[str] = []
    probe_semantic: list[dict[str, Any]] = []
    for window in base.PROBE_WINDOWS:
        start = base.parse_utc(window["start"])
        end = base.parse_utc(window["end"])
        selected = [row for row in rows if start <= int(row["block_timestamp"]) < end]
        probe_counts[window["name"]] = len(selected)
        probe_ids.extend(identity(row) for row in selected)
        probe_semantic.extend(semantic_subset(row) for row in selected)
    expected_counts = authority["probe_window_counts"]
    if probe_counts != expected_counts:
        raise SystemExit(f"probe count mismatch: {probe_counts!r} != {expected_counts!r}")
    probe_identity_sha = hashlib.sha256(("\n".join(sorted(probe_ids)) + "\n").encode()).hexdigest()
    if probe_identity_sha != authority["identity_sha256"]:
        raise SystemExit("probe identity hash mismatch")
    probe_semantic.sort(key=lambda row: (row["block_timestamp"], row["transaction_hash"], int(row["log_index"])))
    probe_semantic_sha = hashlib.sha256(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in probe_semantic).encode()
    ).hexdigest()
    if probe_semantic_sha != authority["semantic_subset_sha256"]:
        raise SystemExit("probe semantic hash mismatch")

    event_path = args.output / "GMX_V1_BTCETH_LIQUIDATIONS_20210701_20231231.jsonl.gz"
    deterministic_gzip(event_path, rows)
    asset_counts = Counter(row["asset"] for row in rows)
    side_counts = Counter(row["liquidated_position_side"] for row in rows)
    result = {
        "schema_version": 1,
        "takeover_claim_id": authority["takeover_claim_id"],
        "parent_claim_id": authority["parent_claim_id"],
        "phase": "FROZEN_PRE2024_FULL_HISTORY",
        "transport": "SQD_FINALIZED_PORTAL_V2",
        "start_utc": START_UTC,
        "end_exclusive_utc": END_EXCLUSIVE_UTC,
        "from_block": from_block,
        "to_block": to_block,
        "raw_logs": raw_logs,
        "btc_eth_liquidations": len(rows),
        "unique_identities": len(set(ids)),
        "asset_counts": dict(sorted(asset_counts.items())),
        "side_counts": dict(sorted(side_counts.items())),
        "first_block_time": rows[0]["block_time_utc"] if rows else None,
        "last_block_time": rows[-1]["block_time_utc"] if rows else None,
        "probe_counts": probe_counts,
        "probe_identity_sha256": probe_identity_sha,
        "probe_semantic_sha256": probe_semantic_sha,
        "event_gzip_sha256": sha256_file(event_path),
        "portal_stats": client.stats,
        "market_outcomes_opened": False,
        "orders_submitted": False,
    }
    result_path = args.output / "FULL_HISTORY_RESULT.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "SHA256SUMS.txt").write_text(
        f"{sha256_file(result_path)}  {result_path.name}\n{sha256_file(event_path)}  {event_path.name}\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
