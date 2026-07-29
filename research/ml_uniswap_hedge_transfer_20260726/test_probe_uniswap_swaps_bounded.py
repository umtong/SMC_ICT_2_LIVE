from __future__ import annotations

import pytest

import probe_uniswap_swaps as base
import probe_uniswap_swaps_bounded as bounded


class PermanentFailureRpc:
    endpoint = "https://example.invalid"

    def __init__(self, message: str) -> None:
        self.message = message
        self.calls = 0

    def call(self, method, params, *, attempts=2):
        self.calls += 1
        raise base.RpcError(self.message)


class RangeLimitedRpc:
    endpoint = "https://range.example"

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def call(self, method, params, *, attempts=2):
        query = params[0]
        start = int(query["fromBlock"], 16)
        end = int(query["toBlock"], 16)
        self.calls.append((start, end))
        if end - start + 1 > 2:
            raise base.RpcError("-32005 query returned more than provider limit")
        return [{"from": start, "to": end}]


class BatchTimestampRpc:
    endpoint = "https://batch.example"

    def __init__(self) -> None:
        self.single_calls: list[int] = []
        self.batch_calls: list[tuple[int, ...]] = []

    def call(self, method, params, *, attempts=5):
        assert method == "eth_getBlockByNumber"
        number = int(params[0], 16)
        self.single_calls.append(number)
        return {"timestamp": hex(number * 12)}

    def batch_block_timestamps(self, block_numbers):
        numbers = tuple(block_numbers)
        self.batch_calls.append(numbers)
        return {number: number * 12 for number in numbers}


def test_permanent_429_does_not_recurse_by_block() -> None:
    rpc = PermanentFailureRpc("HTTP 429: rate limited")
    with pytest.raises(bounded.EndpointUnavailable):
        bounded.get_logs_adaptive(
            rpc,
            address="0x" + "11" * 20,
            from_block=100,
            to_block=500,
            topic0=base.SWAP_TOPIC,
        )
    assert rpc.calls == 1


def test_timeout_with_range_text_is_endpoint_failure() -> None:
    assert not bounded.is_range_error(
        base.RpcError("timeout while serving requested block range")
    )


def test_explicit_range_error_bisects_complete_nonoverlap() -> None:
    rpc = RangeLimitedRpc()
    rows = bounded.get_logs_adaptive(
        rpc,
        address="0x" + "22" * 20,
        from_block=10,
        to_block=15,
        topic0=base.SWAP_TOPIC,
        maximum_chunk=100,
    )
    leaves = sorted((row["from"], row["to"]) for row in rows)
    expanded = [block for start, end in leaves for block in range(start, end + 1)]
    assert expanded == list(range(10, 16))
    assert len(expanded) == len(set(expanded))
    assert all(end - start + 1 <= 2 for start, end in leaves)


def test_block_timestamp_lookup_batches_and_caches() -> None:
    rpc = BatchTimestampRpc()
    locator = bounded.BatchedBlockLocator(rpc, latest_block=100)
    assert locator.timestamp(10) == 120
    assert locator.timestamp(20) == 240
    assert len(rpc.batch_calls) == 1
    assert rpc.batch_calls[0][0] == 10
    assert len(rpc.batch_calls[0]) == bounded.BLOCK_TIMESTAMP_BATCH_SIZE


def test_binary_search_uses_single_timestamp_path() -> None:
    rpc = BatchTimestampRpc()
    locator = bounded.BatchedBlockLocator(rpc, latest_block=100)
    assert locator.first_at_or_after(600) == 50
    assert rpc.batch_calls == []
    assert rpc.single_calls


def test_base_module_is_patched_before_main() -> None:
    assert base.RpcClient is bounded.BoundedRpcClient
    assert base.BlockLocator is bounded.BatchedBlockLocator
    assert base.get_logs_adaptive is bounded.get_logs_adaptive
    assert base.choose_endpoint is bounded.choose_endpoint
