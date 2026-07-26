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

    def _pace(self) -> None:
        delay = MIN_HTTP_INTERVAL_SECONDS - (time.monotonic() - self._last_http_monotonic)
        if delay > 0:
            time.sleep(delay)

    def _post_json(self, payload: Any, *, attempts: int = 6) -> Any:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                self._pace()
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
                if attempt + 1 >= attempts:
                    break
                self.stats.retries += 1
                time.sleep(min(20.0, 1.5 * (2**attempt)))
        raise bounded.base.RpcError(f"paced request failed at {self.endpoint}: {last!r}")

    def call(self, method: str, params: list[Any], *, attempts: int = 2) -> Any:
        if self.stats.calls >= bounded.MAX_RPC_CALLS:
            raise bounded.EndpointUnavailable(f"RPC call budget exceeded at {self.endpoint}")
        if time.monotonic() - self.started_monotonic >= bounded.MAX_WALL_SECONDS:
            raise bounded.EndpointUnavailable(f"RPC wall-time budget exceeded at {self.endpoint}")
        self.counter += 1
        self.stats.calls += 1
        body = self._post_json(
            {
                "jsonrpc": "2.0",
                "id": self.counter,
                "method": method,
                "params": params,
            },
            attempts=max(2, int(attempts)),
        )
        if not isinstance(body, dict):
            raise bounded.base.RpcError(f"single RPC response is not an object: {type(body)!r}")
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
            if self.stats.calls + len(chunk) >= bounded.MAX_RPC_CALLS:
                raise bounded.EndpointUnavailable(
                    f"RPC logical-call budget exceeded at {self.endpoint}"
                )
            payload = []
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
            self.stats.calls += len(chunk)
            body = self._post_json(payload, attempts=6)
            if not isinstance(body, list):
                # Fail closed to exact paced single calls if a provider rejects JSON-RPC batch.
                for block_number in chunk:
                    block = self.call("eth_getBlockByNumber", [hex(block_number), False], attempts=6)
                    if block is None:
                        raise bounded.base.RpcError(f"missing block {block_number}")
                    output[block_number] = bounded.base.hex_int(block["timestamp"])
                continue
            by_id = {int(item.get("id")): item for item in body if isinstance(item, dict)}
            for request_id, block_number in id_to_block.items():
                item = by_id.get(request_id)
                if item is None:
                    raise bounded.base.RpcError(
                        f"batch response missing block {block_number} / id {request_id}"
                    )
                if item.get("error") is not None:
                    raise bounded.base.RpcError(
                        f"batch block {block_number} error: {json.dumps(item['error'], sort_keys=True)}"
                    )
                block = item.get("result")
                if block is None:
                    raise bounded.base.RpcError(f"missing block {block_number}")
                output[block_number] = bounded.base.hex_int(block["timestamp"])
        return output


class PrefetchBlockLocator(bounded.base.BlockLocator):
    """Exact locator that fills 40 consecutive block timestamps per paced request."""

    def timestamp(self, block_number: int) -> int:
        block_number = int(block_number)
        if block_number not in self.cache:
            start = max(0, block_number - 8)
            candidates = range(start, start + BATCH_SIZE)
            client = self.rpc
            if not isinstance(client, PacedBatchRpcClient):
                return super().timestamp(block_number)
            self.cache.update(client.block_timestamps(candidates))
        if block_number not in self.cache:
            raise bounded.base.RpcError(f"timestamp batch did not contain block {block_number}")
        return self.cache[block_number]


def self_test() -> None:
    class FakeRpc:
        def block_timestamps(self, blocks: Iterable[int]) -> dict[int, int]:
            return {int(block): int(block) * 12 for block in blocks}

    locator = object.__new__(PrefetchBlockLocator)
    locator.rpc = FakeRpc()
    locator.latest_block = 1000
    locator.cache = {}
    assert locator.timestamp(100) == 1200
    assert locator.timestamp(101) == 1212
    assert len(locator.cache) == BATCH_SIZE


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
