from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Iterable

import source_gate_blockscout as source
import source_gate_blockscout_authoritative as authority

RPC_ENDPOINT = "https://eth.blockscout.com/api/eth-rpc"
BATCH_SIZE = 40
REQUEST_INTERVAL_SECONDS = 0.36
BaseClient = source.BlockscoutClient


class ExactBatchClient(BaseClient):
    """Authoritative Blockscout source identity with exact JSON-RPC timestamp batches."""

    def _post_batch(self, block_numbers: Iterable[int]) -> dict[int, int]:
        numbers = tuple(dict.fromkeys(int(value) for value in block_numbers))
        if not numbers or len(numbers) > BATCH_SIZE:
            raise ValueError(f"invalid batch size {len(numbers)}")

        payload: list[dict[str, Any]] = []
        id_to_block: dict[int, int] = {}
        for request_id, block_number in enumerate(numbers, start=1):
            id_to_block[request_id] = block_number
            payload.append(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "eth_getBlockByNumber",
                    "params": [hex(block_number), False],
                }
            )

        last: Exception | None = None
        for attempt in range(6):
            try:
                elapsed = time.monotonic() - self.last_request_at
                if elapsed < REQUEST_INTERVAL_SECONDS:
                    time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)
                response = self.session.post(
                    RPC_ENDPOINT,
                    json=payload,
                    timeout=(15, 90),
                )
                self.last_request_at = time.monotonic()
                self.request_count += 1
                if response.status_code == 429 or response.status_code >= 500:
                    raise source.BlockscoutError(
                        f"HTTP {response.status_code}: {response.text[:300]}"
                    )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, list):
                    raise source.BlockscoutError(
                        f"batch response must be list, got {type(body)!r}"
                    )
                by_id = {
                    int(item["id"]): item
                    for item in body
                    if isinstance(item, dict) and "id" in item
                }
                result: dict[int, int] = {}
                for request_id, block_number in id_to_block.items():
                    item = by_id.get(request_id)
                    if item is None:
                        raise source.BlockscoutError(
                            f"missing batch response for block {block_number}"
                        )
                    if item.get("error") is not None:
                        raise source.BlockscoutError(
                            json.dumps(item["error"], sort_keys=True)
                        )
                    block = item.get("result")
                    if block is None:
                        raise source.BlockscoutError(
                            f"missing block result {block_number}"
                        )
                    result[block_number] = source.parse_int(block["timestamp"])
                return result
            except Exception as exc:
                last = exc
                self.errors.append(
                    f"{RPC_ENDPOINT}: {type(exc).__name__}: {exc}"
                )
                if attempt + 1 < 6:
                    time.sleep(min(20.0, 1.5 * (2**attempt)))
        raise source.BlockscoutError(f"exact block timestamp batch failed: {last!r}")

    def block_timestamp(self, block_number: int) -> int:
        number = int(block_number)
        cached = self.block_timestamp_cache.get(number)
        if cached is not None:
            return cached

        start = max(0, number - 8)
        candidates = tuple(range(start, start + BATCH_SIZE))
        try:
            self.block_timestamp_cache.update(self._post_batch(candidates))
        except Exception:
            # Fail closed to the original exact REST lookup. No timestamp is
            # approximated or imputed when the batch transport is rejected.
            return super().block_timestamp(number)
        if number not in self.block_timestamp_cache:
            raise source.BlockscoutError(
                f"batch did not contain requested block {number}"
            )
        return self.block_timestamp_cache[number]


def self_test() -> None:
    client = object.__new__(ExactBatchClient)
    client.block_timestamp_cache = {}
    client.request_count = 0
    client.errors = []
    observed: list[tuple[int, ...]] = []

    def fake_batch(blocks: Iterable[int]) -> dict[int, int]:
        values = tuple(int(value) for value in blocks)
        observed.append(values)
        return {value: value * 12 for value in values}

    client._post_batch = fake_batch  # type: ignore[method-assign]
    if client.block_timestamp(100) != 1200:
        raise AssertionError("requested block timestamp mismatch")
    if client.block_timestamp(101) != 1212:
        raise AssertionError("batch cache was not reused")
    if len(observed) != 1 or observed[0][0] != 92 or observed[0][-1] != 131:
        raise AssertionError(observed)

    if source.source_gate is not authority.source_gate:
        raise AssertionError("shared source gate is not bound to authoritative schema")
    if authority.SOURCE_SCHEMA_ID != "STABLECOIN_SUPPLY_USDT_ISSUE_REDEEM_USDC_ZERO_TRANSFER_V1":
        raise AssertionError("source schema identity changed")

    issue = {
        "address": authority.base.auth.CONTRACTS["USDT"]["address"],
        "topics": [authority.base.auth.ISSUE_TOPIC, None, "", "0x"],
        "data": hex(1_000_000 * 10**6),
        "blockNumber": "0x10",
        "transactionHash": "0x" + "ab" * 32,
        "logIndex": "0x0",
    }
    if authority.base.auth.decode_log("USDT", "MINT", issue)["amount_usd"] != 1_000_000:
        raise AssertionError("USDT Issue decode changed")
    print("schema-bound exact-batch stablecoin source self-test passed")


def run(output: Path) -> dict[str, Any]:
    source.BlockscoutClient = ExactBatchClient
    result = authority.source_gate(output)
    if result.get("source_schema_id") != authority.SOURCE_SCHEMA_ID:
        raise RuntimeError("schema binding missing from source result")
    if result.get("source_correction_id") != authority.SOURCE_CORRECTION_ID:
        raise RuntimeError("correction binding missing from source result")
    manifest = json.loads((output / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("source_schema_id") != authority.SOURCE_SCHEMA_ID:
        raise RuntimeError("schema binding missing from source manifest")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        raise SystemExit("--output is required")
    self_test()
    result = run(args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
