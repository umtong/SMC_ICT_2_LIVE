from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

import run_profit_first as engine


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("claim_id") != engine.CLAIM_ID:
        raise engine.ContractError(f"claim mismatch: {path}")
    if payload.get("contract_sha256") != engine.contract_sha256():
        raise engine.ContractError(f"contract mismatch: {path}")
    return payload


def locate_pool_dir(root: Path, pool_name: str) -> Path:
    matches = [
        p.parent
        for p in root.rglob("POOL_MANIFEST.json")
        if json.loads(p.read_text(encoding="utf-8")).get("pool_name") == pool_name
    ]
    if len(matches) != 1:
        raise engine.ContractError(f"expected one artifact for {pool_name}, found {len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pools-root", type=Path, required=True)
    parser.add_argument("--output-cache", type=Path, required=True)
    args = parser.parse_args()
    args.output_cache.mkdir(parents=True, exist_ok=True)

    expected_start = None
    expected_end = None
    all_events: list[engine.NormalizedSwap] = []
    seen: set[tuple[str, int]] = set()
    pool_counts: dict[str, int] = {}
    invalid_counts: dict[str, int] = {}
    pool_manifests: dict[str, Any] = {}
    request_ledgers: list[str] = []
    raw_stream = hashlib.sha256()
    total_requests = 0

    for pool_name in engine.POOL_SPECS:
        directory = locate_pool_dir(args.pools_root, pool_name)
        manifest = load_manifest(directory / "POOL_MANIFEST.json")
        if manifest.get("pool_spec") != engine.POOL_SPECS[pool_name]:
            raise engine.ContractError(f"pool spec mismatch {pool_name}")
        events_path = directory / manifest["events_file"]
        ledger_path = directory / manifest["ledger_file"]
        if engine.sha256_file(events_path) != manifest["events_sha256"]:
            raise engine.ContractError(f"events hash mismatch {pool_name}")
        if engine.sha256_file(ledger_path) != manifest["ledger_sha256"]:
            raise engine.ContractError(f"ledger hash mismatch {pool_name}")
        expected_start = manifest["start_block"] if expected_start is None else expected_start
        expected_end = manifest["end_block"] if expected_end is None else expected_end
        if manifest["start_block"] != expected_start or manifest["end_block"] != expected_end:
            raise engine.ContractError("pool block-range mismatch")
        count = 0
        with gzip.open(events_path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                event = engine.NormalizedSwap(**row)
                if event.pool_name != pool_name:
                    raise engine.ContractError(f"event pool mismatch {pool_name}")
                key = (event.transaction_hash, event.log_index)
                if key in seen:
                    raise engine.ContractError(f"duplicate event identity {key}")
                seen.add(key)
                all_events.append(event)
                raw_stream.update(
                    json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                )
                count += 1
        if count != int(manifest["event_count"]):
            raise engine.ContractError(f"event count mismatch {pool_name}: {count}")
        pool_counts[pool_name] = count
        invalid_counts[pool_name] = int(manifest.get("zero_leg_dust_count", 0))
        pool_manifests[pool_name] = manifest
        total_requests += int(manifest.get("request_count", 0))
        request_ledgers.append(ledger_path.read_text(encoding="utf-8"))

    all_events.sort(key=lambda event: (
        event.timestamp,
        event.block_number,
        event.transaction_hash,
        event.log_index,
    ))
    events_path = args.output_cache / "UNISWAP_NORMALIZED_SWAPS.jsonl.gz"
    with gzip.open(events_path, "wt", encoding="utf-8") as handle:
        for event in all_events:
            handle.write(json.dumps(asdict(event), sort_keys=True, separators=(",", ":")) + "\n")

    buckets: dict[int, engine.BucketAccumulator] = {}
    for event in all_events:
        bucket_s = event.timestamp - event.timestamp % engine.FIVE_MINUTES_S
        buckets.setdefault(bucket_s, engine.BucketAccumulator(bucket_s)).add(event)
    frame = pd.DataFrame([buckets[key].finalize() for key in sorted(buckets)])
    if frame.empty:
        raise engine.ContractError("merged source produced no buckets")
    table_path = args.output_cache / "UNISWAP_5M_BUCKETS.parquet"
    frame.to_parquet(table_path, index=False)
    ledger_path = args.output_cache / "BLOCKSCOUT_REQUEST_LEDGER.jsonl"
    ledger_path.write_text("".join(request_ledgers), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "claim_id": engine.CLAIM_ID,
        "continuation_id": engine.CONTINUATION_ID,
        "provider": "Blockscout Ethereum Etherscan-compatible API / four independent pool jobs",
        "start": engine.HISTORY_START.isoformat(),
        "end_exclusive": engine.HISTORY_END_EXCLUSIVE.isoformat(),
        "start_block": expected_start,
        "end_block": expected_end,
        "pools": engine.POOL_SPECS,
        "pool_event_counts": pool_counts,
        "invalid_counts": invalid_counts,
        "unique_event_count": len(all_events),
        "bucket_count": len(frame),
        "request_count": total_requests,
        "raw_response_stream_sha256": raw_stream.hexdigest(),
        "normalized_events_file": events_path.name,
        "normalized_events_sha256": engine.sha256_file(events_path),
        "request_ledger_file": ledger_path.name,
        "request_ledger_sha256": engine.sha256_file(ledger_path),
        "buckets_sha256": engine.sha256_file(table_path),
        "contract_sha256": engine.contract_sha256(),
        "pool_manifests": pool_manifests,
        "errors_tail": [
            error
            for pool_manifest in pool_manifests.values()
            for error in pool_manifest.get("errors_tail", [])
        ][-40:],
    }
    (args.output_cache / "UNISWAP_HISTORY_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "unique_event_count": len(all_events),
        "bucket_count": len(frame),
        "pool_counts": pool_counts,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
