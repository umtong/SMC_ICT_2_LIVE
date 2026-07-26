from __future__ import annotations

import json
import time
from typing import Any, Iterable

import probe_uniswap_swaps as base

MAX_RPC_CALLS = 3_000
MAX_WALL_SECONDS = 1_200.0
RANGE_ERROR_MARKERS = (
    "-32005",
    "query returned more than",
    "too many results",
    "response size",
    "result size",
    "range too large",
    "block range",
    "limit exceeded",
    "please limit the query",
    "maximum block range",
)
ENDPOINT_ERROR_MARKERS = (
    "http 429",
    "http 401",
    "http 403",
    "timeout",
    "timed out",
    "archive",
    "missing trie node",
    "header not found",
    "connection",
    "name resolution",
    "malformed",
)


class EndpointUnavailable(base.RpcError):
    pass


class BoundedRpcClient(base.RpcClient):
    def __init__(self, endpoint: str) -> None:
        super().__init__(endpoint)
        self.started_monotonic = time.monotonic()

    def call(self, method: str, params: list[Any], *, attempts: int = 2) -> Any:
        if self.stats.calls >= MAX_RPC_CALLS:
            raise EndpointUnavailable(f"RPC call budget exceeded at {self.endpoint}")
        if time.monotonic() - self.started_monotonic >= MAX_WALL_SECONDS:
            raise EndpointUnavailable(f"RPC wall-time budget exceeded at {self.endpoint}")
        try:
            return super().call(method, params, attempts=min(int(attempts), 2))
        except Exception as exc:
            raise base.RpcError(str(exc)) from exc


def is_range_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if any(marker in text for marker in ENDPOINT_ERROR_MARKERS):
        return False
    return any(marker in text for marker in RANGE_ERROR_MARKERS)


def get_logs_adaptive(
    rpc: BoundedRpcClient,
    *,
    address: str,
    from_block: int,
    to_block: int,
    topic0: str,
    maximum_chunk: int = 1_000,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []

    def query(start: int, end: int, depth: int = 0) -> None:
        if depth > 32:
            raise EndpointUnavailable("range bisection depth exceeded")
        try:
            result = rpc.call(
                "eth_getLogs",
                [
                    {
                        "fromBlock": hex(start),
                        "toBlock": hex(end),
                        "address": base.normalize_address(address),
                        "topics": [topic0],
                    }
                ],
            )
            if not isinstance(result, list):
                raise EndpointUnavailable(
                    f"eth_getLogs returned {type(result)!r} at {rpc.endpoint}"
                )
            output.extend(result)
        except Exception as exc:
            if not is_range_error(exc):
                raise EndpointUnavailable(
                    f"historical eth_getLogs unavailable at {rpc.endpoint}: {exc}"
                ) from exc
            if start >= end:
                raise EndpointUnavailable(
                    f"single-block eth_getLogs still exceeds provider range at {start}"
                ) from exc
            midpoint = (start + end) // 2
            query(start, midpoint, depth + 1)
            query(midpoint + 1, end, depth + 1)

    cursor = int(from_block)
    while cursor <= int(to_block):
        end = min(int(to_block), cursor + int(maximum_chunk) - 1)
        query(cursor, end)
        cursor = end + 1
    return output


def choose_endpoint(
    endpoints: Iterable[str],
) -> tuple[BoundedRpcClient, dict[str, Any], dict[str, dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    start_timestamp, _ = base.one_hour_window(*base.PROBE_WINDOWS[0])

    for endpoint in endpoints:
        rpc = BoundedRpcClient(endpoint)
        item: dict[str, Any] = {"endpoint": endpoint}
        try:
            chain_id = base.hex_int(rpc.call("eth_chainId", []))
            latest = base.hex_int(rpc.call("eth_blockNumber", []))
            factory_code = rpc.call("eth_getCode", [base.FACTORY, "latest"])
            token_codes = {
                name: len(
                    rpc.call("eth_getCode", [address, "latest"]).removeprefix("0x")
                )
                // 2
                for name, address in base.TOKENS.items()
            }
            pools = base.resolve_pools(rpc)
            passing = [name for name, row in pools.items() if row["status"] == "PASS"]
            if not (
                chain_id == 1
                and len(factory_code.removeprefix("0x")) > 0
                and all(size > 0 for size in token_codes.values())
                and len(passing) >= 2
            ):
                raise EndpointUnavailable("chain, bytecode, or canonical pool preflight failed")

            locator = base.BlockLocator(rpc, latest)
            historical_block = locator.first_at_or_after(start_timestamp)
            historical = rpc.call("eth_getBlockByNumber", [hex(historical_block), False])
            if historical is None:
                raise EndpointUnavailable("historical block preflight returned null")
            pool = pools[passing[0]]["pool"]
            one_block = rpc.call(
                "eth_getLogs",
                [
                    {
                        "fromBlock": hex(historical_block),
                        "toBlock": hex(historical_block),
                        "address": base.normalize_address(pool),
                        "topics": [base.SWAP_TOPIC],
                    }
                ],
            )
            if not isinstance(one_block, list):
                raise EndpointUnavailable("historical one-block log preflight was not a list")

            item.update(
                {
                    "status": "PASS",
                    "chain_id": chain_id,
                    "latest_block": latest,
                    "historical_preflight_block": historical_block,
                    "historical_preflight_log_count": len(one_block),
                    "factory_code_bytes": len(factory_code.removeprefix("0x")) // 2,
                    "token_code_bytes": token_codes,
                    "passing_pools": passing,
                    "pools": pools,
                    "rpc_stats": vars(rpc.stats),
                }
            )
            attempts.append(item)
            return rpc, {"selected": endpoint, "attempts": attempts}, pools
        except Exception as exc:
            item.update(
                {
                    "status": "ERROR",
                    "error": repr(exc),
                    "rpc_stats": vars(rpc.stats),
                }
            )
            attempts.append(item)

    raise base.RpcError(json.dumps({"endpoint_attempts": attempts}, indent=2))


# Mechanical transport-only patch. The base module resolves these globals at run time.
base.RpcClient = BoundedRpcClient
base.get_logs_adaptive = get_logs_adaptive
base.choose_endpoint = choose_endpoint


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
