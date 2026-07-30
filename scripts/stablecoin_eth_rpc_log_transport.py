from __future__ import annotations

import json
import time
from typing import Any, Iterable, Mapping, Sequence

RPC_ENDPOINTS = (
    "https://ethereum-rpc.publicnode.com",
    "https://public.1rpc.io/eth",
)
RPC_REQUEST_INTERVAL_SECONDS = 0.36
RPC_CONNECT_TIMEOUT_SECONDS = 15
RPC_READ_TIMEOUT_SECONDS = 120
RPC_RETRIES_PER_ENDPOINT = 3
RPC_BLOCK_BATCH_SIZE = 40
MAX_SAFE_LOG_ROWS = 1_000

_SPLIT_WORTHY_MARKERS = (
    "timeout",
    "timed out",
    "too many results",
    "response size",
    "range",
    "block limit",
    "query returned more than",
    "please limit",
    "exceed",
)


class EthereumRpcTransportError(RuntimeError):
    """Fail-closed public Ethereum JSON-RPC transport failure."""


def _parse_quantity(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def topics_from_legacy_params(params: Mapping[str, Any]) -> list[Any]:
    """Translate the frozen Blockscout topic fields to eth_getLogs topics."""
    if "topic0" not in params:
        raise EthereumRpcTransportError("frozen log filter lacks topic0")
    highest = 0
    for index in range(1, 5):
        if f"topic{index}" in params:
            highest = index
    topics: list[Any] = [params["topic0"]]
    for index in range(1, highest + 1):
        topics.append(params.get(f"topic{index}"))
    return topics


def _is_split_worthy(error: BaseException) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in _SPLIT_WORTHY_MARKERS)


class EthereumRpcLogMixin:
    """Replace only source-log transport; preserve frozen filters and decoding."""

    rpc_endpoints: Sequence[str] = RPC_ENDPOINTS

    def _rpc_throttle(self) -> None:
        last = float(getattr(self, "last_request_at", 0.0))
        elapsed = time.monotonic() - last
        if elapsed < RPC_REQUEST_INTERVAL_SECONDS:
            time.sleep(RPC_REQUEST_INTERVAL_SECONDS - elapsed)

    def _rpc_post_to_endpoint(self, endpoint: str, payload: Any) -> Any:
        self._rpc_throttle()
        response = self.session.post(
            endpoint,
            json=payload,
            timeout=(RPC_CONNECT_TIMEOUT_SECONDS, RPC_READ_TIMEOUT_SECONDS),
        )
        self.last_request_at = time.monotonic()
        self.request_count = int(getattr(self, "request_count", 0)) + 1
        if response.status_code == 429 or response.status_code >= 500:
            raise EthereumRpcTransportError(
                f"{endpoint} HTTP {response.status_code}: {response.text[:300]}"
            )
        response.raise_for_status()
        return response.json()

    def _rpc_request(self, payload: Any) -> tuple[Any, str]:
        errors: list[str] = []
        for endpoint in self.rpc_endpoints:
            for attempt in range(RPC_RETRIES_PER_ENDPOINT):
                try:
                    body = self._rpc_post_to_endpoint(endpoint, payload)
                    return body, endpoint
                except Exception as exc:
                    message = f"{endpoint}: {type(exc).__name__}: {exc}"
                    errors.append(message)
                    getattr(self, "errors", []).append(message)
                    if attempt + 1 < RPC_RETRIES_PER_ENDPOINT:
                        time.sleep(min(8.0, 1.5 * (2**attempt)))
        raise EthereumRpcTransportError(
            "all public Ethereum RPC endpoints failed: " + " | ".join(errors[-8:])
        )

    def _post_batch(self, block_numbers: Iterable[int]) -> dict[int, int]:
        """Resolve exact block timestamps through provider-independent JSON-RPC."""
        numbers = tuple(dict.fromkeys(int(value) for value in block_numbers))
        if not numbers:
            return {}
        result: dict[int, int] = {}
        for start in range(0, len(numbers), RPC_BLOCK_BATCH_SIZE):
            chunk = numbers[start : start + RPC_BLOCK_BATCH_SIZE]
            requests = [
                {
                    "jsonrpc": "2.0",
                    "id": index,
                    "method": "eth_getBlockByNumber",
                    "params": [hex(block_number), False],
                }
                for index, block_number in enumerate(chunk, start=1)
            ]
            try:
                body, _endpoint = self._rpc_request(requests)
                if not isinstance(body, list):
                    raise EthereumRpcTransportError(
                        f"batch block response must be a list, got {type(body)!r}"
                    )
                by_id = {
                    int(item["id"]): item
                    for item in body
                    if isinstance(item, dict) and "id" in item
                }
                for index, block_number in enumerate(chunk, start=1):
                    item = by_id.get(index)
                    if item is None:
                        raise EthereumRpcTransportError(
                            f"missing block response for {block_number}"
                        )
                    if item.get("error") is not None:
                        raise EthereumRpcTransportError(
                            json.dumps(item["error"], sort_keys=True)
                        )
                    block = item.get("result")
                    if not isinstance(block, dict) or "timestamp" not in block:
                        raise EthereumRpcTransportError(
                            f"missing timestamp for block {block_number}"
                        )
                    result[block_number] = _parse_quantity(block["timestamp"])
            except Exception:
                # Some public endpoints disable JSON-RPC batches. Preserve exactness
                # with individual eth_getBlockByNumber calls; never interpolate.
                for block_number in chunk:
                    request = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_getBlockByNumber",
                        "params": [hex(block_number), False],
                    }
                    item, _endpoint = self._rpc_request(request)
                    if not isinstance(item, dict) or item.get("error") is not None:
                        raise EthereumRpcTransportError(
                            f"block lookup failed for {block_number}: {item}"
                        )
                    block = item.get("result")
                    if not isinstance(block, dict) or "timestamp" not in block:
                        raise EthereumRpcTransportError(
                            f"missing timestamp for block {block_number}"
                        )
                    result[block_number] = _parse_quantity(block["timestamp"])
        return result

    def _enrich_log_timestamps(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        blocks = sorted({_parse_quantity(row["blockNumber"]) for row in rows})
        cache = getattr(self, "block_timestamp_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self.block_timestamp_cache = cache
        missing = [block for block in blocks if block not in cache]
        if missing:
            cache.update(self._post_batch(missing))
        enriched: list[dict[str, Any]] = []
        for row in rows:
            block_number = _parse_quantity(row["blockNumber"])
            if block_number not in cache:
                raise EthereumRpcTransportError(
                    f"timestamp cache lacks block {block_number}"
                )
            copied = dict(row)
            copied["timeStamp"] = hex(int(cache[block_number]))
            enriched.append(copied)
        return enriched

    def _rpc_get_logs_once(
        self,
        address: str,
        direction: str,
        start_block: int,
        end_block: int,
    ) -> tuple[list[dict[str, Any]], str]:
        legacy = self._log_params(address, direction, start_block, end_block)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getLogs",
            "params": [
                {
                    "fromBlock": hex(int(start_block)),
                    "toBlock": hex(int(end_block)),
                    "address": address,
                    "topics": topics_from_legacy_params(legacy),
                }
            ],
        }
        body, endpoint = self._rpc_request(request)
        if not isinstance(body, dict):
            raise EthereumRpcTransportError(
                f"eth_getLogs response must be an object, got {type(body)!r}"
            )
        if body.get("error") is not None:
            raise EthereumRpcTransportError(
                json.dumps(body["error"], sort_keys=True)
            )
        rows = body.get("result")
        if not isinstance(rows, list):
            raise EthereumRpcTransportError(
                f"eth_getLogs result must be a list, got {type(rows)!r}"
            )
        normalized = [dict(row) for row in rows if isinstance(row, dict)]
        if len(normalized) != len(rows):
            raise EthereumRpcTransportError("eth_getLogs returned a non-object row")
        return self._enrich_log_timestamps(normalized), endpoint

    def logs(
        self,
        address: str,
        direction: str,
        start_block: int,
        end_block: int,
        diagnostics: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        try:
            rows, endpoint = self._rpc_get_logs_once(
                address, direction, start_block, end_block
            )
        except Exception as exc:
            if start_block < end_block and _is_split_worthy(exc):
                mid = (start_block + end_block) // 2
                diagnostics.append(
                    {
                        "from_block": int(start_block),
                        "to_block": int(end_block),
                        "status": "SPLIT_RPC_TRANSPORT_LIMIT",
                        "log_count": None,
                        "provider_error": f"{type(exc).__name__}: {exc}"[:500],
                    }
                )
                return self.logs(
                    address, direction, start_block, mid, diagnostics
                ) + self.logs(address, direction, mid + 1, end_block, diagnostics)
            raise

        status = "PASS_EMPTY" if not rows else "PASS"
        diagnostics.append(
            {
                "from_block": int(start_block),
                "to_block": int(end_block),
                "status": status,
                "log_count": len(rows),
                "provider": endpoint,
                "method": "eth_getLogs",
            }
        )
        if len(rows) < MAX_SAFE_LOG_ROWS:
            return rows
        if start_block >= end_block:
            raise EthereumRpcTransportError(
                "single block reached the frozen 1000-log safety ceiling"
            )
        mid = (start_block + end_block) // 2
        diagnostics[-1]["status"] = "SPLIT_AT_FROZEN_LOG_SAFETY_CEILING"
        return self.logs(
            address, direction, start_block, mid, diagnostics
        ) + self.logs(address, direction, mid + 1, end_block, diagnostics)
