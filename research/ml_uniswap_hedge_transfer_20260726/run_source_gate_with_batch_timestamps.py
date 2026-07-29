from __future__ import annotations

import json
import time
from typing import Any, Iterable

import probe_uniswap_swaps_bounded as bounded

BLOCKSCOUT_ETH_RPC = "https://eth.blockscout.com/api/eth-rpc"
BATCH_SIZE = 40
MIN_HTTP_INTERVAL_SECONDS = 0.40


class PacedBatchRpcClient(bounded.BoundedRpcClient):
    """Bounded JSON-RPC client with paced HTTP and exact block-timestamp batches."""

    def __init__(self, endpoint: str) -> None:
        super().__init__(endpoint)
        self._last_http_monotonic = 0.0

    def _pace_http(self) -> None:
        if self.stats.calls >= bounded.MAX_RPC_CALLS:
            raise bounded.EndpointUnavailable(f"RPC HTTP-call budget exceeded at {self.endpoint}")
        if time.monotonic() - self.started_monotonic >= bounded.MAX_WALL_SECONDS:
            raise bounded.EndpointUnavailable(f"RPC wall-time budget exceeded at {self.endpoint}")
        delay = MIN_HTTP_INTERVAL_SECONDS - (time.monotonic() - self._last_http_monotonic)
        if delay > 0:
            time.sleep(delay)

    def _post_json(self, payload: Any, *, attempts: int = 6) -> Any:
        last: Exception | None = None
        for attempt in range(max(1, int(attempts))):
            try:
                self._pace_http()
                self.stats.calls += 1
                response = self.session.post(
                    self.endpoint,
                    json=payload,
                    timeout=(15, 90),
                )
                self._last_http_monotonic = time.monotonic()
                if response.status_code == 429 or response.status_code >= 500:
                    raise bounded.base.RpcError(
                        f"HTTP {response.status_code}: {response.text[:300]}"
                    )
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last = exc
                self.stats.errors += 1
                if attempt + 1 >= max(1, int(attempts)):
                    break
                self.stats.retries += 1
                time.sleep(min(20.0, 1.5 * (2**attempt)))
        raise bounded.base.RpcError(f"paced request failed at {self.endpoint}: {last!r}")

    def call(self, method: str, params: list[Any], *, attempts: int = 2) -> Any:
        self.counter += 1
        request_id = self.counter
        body = self._post_json(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
            attempts=max(2, int(attempts)),
        )
        if not isinstance(body, dict):
            raise bounded.base.RpcError(
                f"single RPC response is not an object: {type(body)!r}"
            )
        if body.get("id") != request_id:
            raise bounded.base.RpcError("single RPC response id mismatch")
        if body.get("error") is not None:
            raise bounded.base.RpcError(json.dumps(body["error"], sort_keys=True))
        if "result" not in body:
            raise bounded.base.RpcError(f"single RPC missing result: {body!r}")
        return body["result"]

    def block_timestamps(self, block_numbers: Iterable[int]) -> dict[int, int]:
        numbers = list(dict.fromkeys(int(value) for value in block_numbers))
        output: dict[int, int] = {}
        for offset in range(0, len(numbers), BATCH_SIZE):
            chunk = numbers[offset : offset + BATCH_SIZE]
            payload: list[dict[str, Any]] = []
            id_to_block: dict[int, int] = {}
            for block_number in chunk:
                self.counter += 1
                request_id = self.counter
                id_to_block[request_id] = block_number
                payload.append(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "eth_getBlockByNumber",
                        "params": [hex(block_number), False],
                    }
                )

            batch_failed: Exception | None = None
            try:
                body = self._post_json(payload, attempts=6)
                if not isinstance(body, list):
                    raise bounded.base.RpcError(
                        f"batch block response is not a list: {type(body)!r}"
                    )
                by_id = {
                    int(item["id"]): item
                    for item in body
                    if isinstance(item, dict) and "id" in item
                }
                batch_values: dict[int, int] = {}
                for request_id, block_number in id_to_block.items():
                    item = by_id.get(request_id)
                    if item is None:
                        raise bounded.base.RpcError(
                            f"batch response missing block {block_number} / id {request_id}"
                        )
                    if item.get("error") is not None:
                        raise bounded.base.RpcError(
                            f"batch block {block_number} error: "
                            f"{json.dumps(item['error'], sort_keys=True)}"
                        )
                    block = item.get("result")
                    if not isinstance(block, dict):
                        raise bounded.base.RpcError(f"missing block {block_number}")
                    batch_values[block_number] = bounded.base.hex_int(block["timestamp"])
                output.update(batch_values)
                continue
            except Exception as exc:
                batch_failed = exc

            # Fail closed: discard every partial batch value and request each exact block.
            for block_number in chunk:
                try:
                    block = self.call(
                        "eth_getBlockByNumber",
                        [hex(block_number), False],
                        attempts=6,
                    )
                except Exception as exc:
                    raise bounded.base.RpcError(
                        f"batch and exact fallback failed for block {block_number}; "
                        f"batch={batch_failed!r}; exact={exc!r}"
                    ) from exc
                if not isinstance(block, dict):
                    raise bounded.base.RpcError(f"missing exact block {block_number}")
                output[block_number] = bounded.base.hex_int(block["timestamp"])
        return output


class PrefetchBlockLocator(bounded.base.BlockLocator):
    """Exact boundary singles plus paced batches for timestamps of observed logs."""

    def _single_timestamp(self, block_number: int) -> int:
        block_number = int(block_number)
        if block_number not in self.cache:
            block = self.rpc.call(
                "eth_getBlockByNumber",
                [hex(block_number), False],
                attempts=6,
            )
            if not isinstance(block, dict):
                raise bounded.base.RpcError(f"missing boundary block {block_number}")
            self.cache[block_number] = bounded.base.hex_int(block["timestamp"])
        return self.cache[block_number]

    def first_at_or_after(self, target_timestamp: int) -> int:
        low = 0
        high = int(self.latest_block)
        if self._single_timestamp(high) < int(target_timestamp):
            raise bounded.EndpointUnavailable(
                f"target {target_timestamp} after latest block timestamp"
            )
        while low < high:
            midpoint = (low + high) // 2
            if self._single_timestamp(midpoint) < int(target_timestamp):
                low = midpoint + 1
            else:
                high = midpoint
        return low

    def timestamp(self, block_number: int) -> int:
        block_number = int(block_number)
        if block_number not in self.cache:
            start = max(0, block_number - 8)
            candidates = range(start, min(self.latest_block + 1, start + BATCH_SIZE))
            batch_lookup = getattr(self.rpc, "block_timestamps", None)
            if not callable(batch_lookup):
                return self._single_timestamp(block_number)
            self.cache.update(batch_lookup(candidates))
        if block_number not in self.cache:
            raise bounded.base.RpcError(
                f"timestamp batch did not contain block {block_number}"
            )
        return self.cache[block_number]


def self_test() -> None:
    class FakeRpc:
        def __init__(self) -> None:
            self.batch_requests: list[tuple[int, ...]] = []
            self.single_requests: list[int] = []

        def block_timestamps(self, blocks: Iterable[int]) -> dict[int, int]:
            values = tuple(int(block) for block in blocks)
            self.batch_requests.append(values)
            return {block: block * 12 for block in values}

        def call(self, method: str, params: list[Any], *, attempts: int = 6) -> dict[str, str]:
            if method != "eth_getBlockByNumber":
                raise AssertionError(method)
            number = int(str(params[0]), 16)
            self.single_requests.append(number)
            return {"timestamp": hex(number * 12)}

    rpc = FakeRpc()
    locator = object.__new__(PrefetchBlockLocator)
    locator.rpc = rpc
    locator.latest_block = 1000
    locator.cache = {}
    assert locator.timestamp(100) == 1200
    assert locator.timestamp(101) == 1212
    assert len(locator.cache) == BATCH_SIZE
    assert len(rpc.batch_requests) == 1
    assert rpc.batch_requests[0][0] == 92
    assert rpc.batch_requests[0][-1] == 131

    boundary_rpc = FakeRpc()
    boundary = object.__new__(PrefetchBlockLocator)
    boundary.rpc = boundary_rpc
    boundary.latest_block = 1000
    boundary.cache = {}
    assert boundary.first_at_or_after(333 * 12) == 333
    assert boundary_rpc.single_requests
    assert boundary_rpc.batch_requests == []


def main() -> int:
    self_test()
    bounded.BoundedRpcClient = PacedBatchRpcClient
    bounded.base.RpcClient = PacedBatchRpcClient
    bounded.base.BlockLocator = PrefetchBlockLocator
    bounded.base.ENDPOINTS = (BLOCKSCOUT_ETH_RPC,) + tuple(
        endpoint for endpoint in bounded.base.ENDPOINTS if endpoint != BLOCKSCOUT_ETH_RPC
    )
    return bounded.main()


if __name__ == "__main__":
    raise SystemExit(main())
