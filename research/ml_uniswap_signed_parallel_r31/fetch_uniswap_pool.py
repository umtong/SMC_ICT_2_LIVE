from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import run_profit_first as engine


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", choices=sorted(engine.POOL_SPECS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    pool_name = args.pool
    spec = engine.POOL_SPECS[pool_name]
    client = engine.BlockscoutClient(min_interval=0.36)
    start_block = client.block_by_time(int(engine.HISTORY_START.timestamp()), "after")
    end_exclusive = client.block_by_time(int(engine.HISTORY_END_EXCLUSIVE.timestamp()), "after")
    end_block = end_exclusive - 1

    events_path = args.output / "POOL_EVENTS.jsonl.gz"
    ledger_path = args.output / "BLOCKSCOUT_REQUEST_LEDGER.jsonl"
    temp_path = events_path.with_suffix(events_path.suffix + ".tmp")
    seen: set[tuple[str, int]] = set()
    count = 0
    zero_leg = 0
    first_block = None
    last_block = None
    raw_stream = hashlib.sha256()

    with gzip.open(temp_path, "wt", encoding="utf-8") as handle:
        for raw in client.logs(str(spec["address"]), start_block, end_block):
            canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
            raw_stream.update(canonical + b"\n")
            try:
                event = engine.decode_swap_log(pool_name, raw)
            except ValueError as exc:
                if str(exc) == "NON_ECONOMIC_ZERO_LEG_SWAP":
                    zero_leg += 1
                    continue
                raise
            key = (event.transaction_hash, event.log_index)
            if key in seen:
                raise engine.ContractError(f"duplicate event identity {key}")
            seen.add(key)
            if not (
                int(engine.HISTORY_START.timestamp())
                <= event.timestamp
                < int(engine.HISTORY_END_EXCLUSIVE.timestamp())
            ):
                raise engine.ContractError("event timestamp outside frozen history")
            handle.write(json.dumps(asdict(event), sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
            first_block = event.block_number if first_block is None else min(first_block, event.block_number)
            last_block = event.block_number if last_block is None else max(last_block, event.block_number)
            if count % 250_000 == 0:
                print(json.dumps({"pool": pool_name, "decoded": count, "requests": client.request_count}), flush=True)
    temp_path.replace(events_path)
    ledger_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in client.request_ledger),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "claim_id": engine.CLAIM_ID,
        "continuation_id": engine.CONTINUATION_ID,
        "pool_name": pool_name,
        "pool_spec": spec,
        "start": engine.HISTORY_START.isoformat(),
        "end_exclusive": engine.HISTORY_END_EXCLUSIVE.isoformat(),
        "start_block": start_block,
        "end_block": end_block,
        "first_event_block": first_block,
        "last_event_block": last_block,
        "event_count": count,
        "zero_leg_dust_count": zero_leg,
        "request_count": client.request_count,
        "raw_response_stream_sha256": raw_stream.hexdigest(),
        "events_file": events_path.name,
        "events_sha256": engine.sha256_file(events_path),
        "ledger_file": ledger_path.name,
        "ledger_sha256": engine.sha256_file(ledger_path),
        "contract_sha256": engine.contract_sha256(),
        "errors_tail": client.errors[-20:],
    }
    write_json(args.output / "POOL_MANIFEST.json", manifest)
    print(json.dumps({"pool": pool_name, "event_count": count, "zero_leg_dust_count": zero_leg}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
