from __future__ import annotations

import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests

HERE = Path(__file__).resolve().parent
BASE_PATH = HERE / "probe_aave_liquidations.py"
SPEC = importlib.util.spec_from_file_location("aave_probe_base", BASE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {BASE_PATH}")
base = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = base
SPEC.loader.exec_module(base)

RANGE_HINTS = (
    "block range",
    "range is too wide",
    "query returned more than",
    "too many results",
    "response size exceeded",
    "limit exceeded",
    "please reduce",
    "max range",
)
RATE_HINTS = ("rate limit", "too many requests", "quota", "capacity")
ARCHIVE_HINTS = (
    "archive",
    "historical state",
    "missing trie",
    "pruned",
    "not available for this block",
)


class SourceTransportError(base.RpcError):
    """Base class for fail-closed source-transport errors."""


class RangeTooLarge(SourceTransportError):
    """The provider explicitly requires a smaller eth_getLogs range."""


class EndpointUnavailable(SourceTransportError):
    """The endpoint is unavailable, unauthorized, rate-limited, or non-archive."""


class BudgetExhausted(SourceTransportError):
    """The frozen call or wall-clock budget was exhausted."""


@dataclass(frozen=True)
class EndpointAttempt:
    endpoint: str
    method: str
    attempt: int
    outcome: str
    detail: str
    range_from: str | None = None
    range_to: str | None = None


def _log_range(params: list[Any]) -> tuple[str | None, str | None]:
    if not params or not isinstance(params[0], dict):
        return None, None
    return params[0].get("fromBlock"), params[0].get("toBlock")


def _error_text(payload: Any) -> str:
    try:
        return json.dumps(payload, sort_keys=True).lower()
    except Exception:
        return repr(payload).lower()


def classify_json_rpc_error(error: Any) -> type[SourceTransportError]:
    text = _error_text(error)
    # Rate/quota and archive failures must never be mistaken for a range-size
    # rejection merely because the message contains the word "limit".
    if any(hint in text for hint in RATE_HINTS + ARCHIVE_HINTS):
        return EndpointUnavailable
    if any(hint in text for hint in RANGE_HINTS):
        return RangeTooLarge
    return EndpointUnavailable


class BoundedFailoverRpcClient:
    """Keyless JSON-RPC client with deterministic failover and strict budgets."""

    def __init__(
        self,
        endpoints: Iterable[str],
        *,
        max_calls: int = 3000,
        max_wall_seconds: float = 1200.0,
        per_endpoint_attempts: int = 2,
    ) -> None:
        self.endpoints = tuple(dict.fromkeys(endpoints))
        if not self.endpoints:
            raise ValueError("at least one endpoint is required")
        self.endpoint = self.endpoints[0]
        self.sessions = {endpoint: requests.Session() for endpoint in self.endpoints}
        for session in self.sessions.values():
            session.headers.update(
                {
                    "User-Agent": "SMC-ICT-2-Aave-source-gate/2.0",
                    "Content-Type": "application/json",
                }
            )
        self.stats = base.RpcStats()
        self.counter = 0
        self.max_calls = int(max_calls)
        self.deadline = time.monotonic() + float(max_wall_seconds)
        self.per_endpoint_attempts = int(per_endpoint_attempts)
        self.trace: list[EndpointAttempt] = []
        self._preferred_index = 0

    def _check_budget(self) -> None:
        if self.stats.calls >= self.max_calls:
            raise BudgetExhausted(f"RPC call budget exhausted at {self.max_calls}")
        if time.monotonic() >= self.deadline:
            raise BudgetExhausted("RPC wall-clock budget exhausted")

    def _record(
        self,
        endpoint: str,
        method: str,
        attempt: int,
        outcome: str,
        detail: str,
        params: list[Any],
    ) -> None:
        start, end = _log_range(params)
        self.trace.append(
            EndpointAttempt(
                endpoint=endpoint,
                method=method,
                attempt=attempt,
                outcome=outcome,
                detail=detail[:500],
                range_from=start,
                range_to=end,
            )
        )

    def call(self, method: str, params: list[Any], *, attempts: int = 5) -> Any:
        del attempts  # The frozen bounded policy controls attempts.
        self.counter += 1
        payload_id = self.counter
        range_errors: list[str] = []
        ordinary_errors: list[str] = []

        order = [
            self.endpoints[(self._preferred_index + offset) % len(self.endpoints)]
            for offset in range(len(self.endpoints))
        ]
        for endpoint in order:
            session = self.sessions[endpoint]
            for attempt in range(1, self.per_endpoint_attempts + 1):
                self._check_budget()
                self.stats.calls += 1
                payload = {
                    "jsonrpc": "2.0",
                    "id": payload_id,
                    "method": method,
                    "params": params,
                }
                try:
                    response = session.post(endpoint, json=payload, timeout=(10, 30))
                    status = int(response.status_code)
                    if status == 429 or status >= 500:
                        self.stats.errors += 1
                        detail = f"HTTP {status}: {response.text[:300]}"
                        ordinary_errors.append(f"{endpoint}: {detail}")
                        self._record(endpoint, method, attempt, "TRANSIENT_HTTP", detail, params)
                        if attempt < self.per_endpoint_attempts:
                            self.stats.retries += 1
                            time.sleep(0.25 * attempt)
                        continue
                    if status in (401, 403):
                        self.stats.errors += 1
                        detail = f"HTTP {status}: {response.text[:300]}"
                        ordinary_errors.append(f"{endpoint}: {detail}")
                        self._record(endpoint, method, attempt, "PERMANENT_HTTP", detail, params)
                        break
                    response.raise_for_status()
                    body = response.json()
                    if body.get("error") is not None:
                        error_type = classify_json_rpc_error(body["error"])
                        detail = _error_text(body["error"])
                        self.stats.errors += 1
                        if error_type is RangeTooLarge:
                            range_errors.append(f"{endpoint}: {detail}")
                            self._record(endpoint, method, attempt, "RANGE_TOO_LARGE", detail, params)
                            break
                        ordinary_errors.append(f"{endpoint}: {detail}")
                        self._record(endpoint, method, attempt, "RPC_UNAVAILABLE", detail, params)
                        break
                    if "result" not in body:
                        self.stats.errors += 1
                        detail = f"missing result: {body!r}"
                        ordinary_errors.append(f"{endpoint}: {detail}")
                        self._record(endpoint, method, attempt, "MALFORMED", detail, params)
                        break
                    self.endpoint = endpoint
                    self._preferred_index = self.endpoints.index(endpoint)
                    self._record(endpoint, method, attempt, "SUCCESS", "", params)
                    return body["result"]
                except BudgetExhausted:
                    raise
                except (requests.Timeout, requests.ConnectionError) as exc:
                    self.stats.errors += 1
                    detail = repr(exc)
                    ordinary_errors.append(f"{endpoint}: {detail}")
                    self._record(endpoint, method, attempt, "TRANSPORT", detail, params)
                    if attempt < self.per_endpoint_attempts:
                        self.stats.retries += 1
                        time.sleep(0.25 * attempt)
                except Exception as exc:
                    self.stats.errors += 1
                    detail = repr(exc)
                    ordinary_errors.append(f"{endpoint}: {detail}")
                    self._record(endpoint, method, attempt, "PERMANENT", detail, params)
                    break

        if range_errors and not ordinary_errors:
            raise RangeTooLarge("; ".join(range_errors))
        if range_errors and method == "eth_getLogs":
            # Reducing an explicitly rejected range is safe; all ordinary transport
            # failures remain visible in the preserved endpoint evidence.
            raise RangeTooLarge("; ".join(range_errors + ordinary_errors))
        raise EndpointUnavailable("; ".join(ordinary_errors + range_errors))


def get_logs_bounded(
    rpc: BoundedFailoverRpcClient,
    *,
    address: str,
    from_block: int,
    to_block: int,
    topic0: str,
    maximum_chunk: int = 2000,
) -> list[dict[str, Any]]:
    """Query non-overlapping ranges; bisect only explicit range-size errors."""
    if from_block > to_block:
        return []
    output: list[dict[str, Any]] = []
    stack: list[tuple[int, int]] = []
    cursor = from_block
    while cursor <= to_block:
        end = min(to_block, cursor + maximum_chunk - 1)
        stack.append((cursor, end))
        cursor = end + 1

    while stack:
        start, end = stack.pop()
        try:
            result = rpc.call(
                "eth_getLogs",
                [
                    {
                        "fromBlock": hex(start),
                        "toBlock": hex(end),
                        "address": address,
                        "topics": [topic0],
                    }
                ],
            )
            if not isinstance(result, list):
                raise EndpointUnavailable(f"eth_getLogs returned {type(result)!r}")
            output.extend(result)
        except RangeTooLarge:
            if start >= end:
                raise
            midpoint = (start + end) // 2
            # LIFO: push right then left so evidence is queried chronologically.
            stack.append((midpoint + 1, end))
            stack.append((start, midpoint))
    return output


def choose_endpoint_bounded(
    endpoints: Iterable[str], pools: dict[str, str]
) -> tuple[BoundedFailoverRpcClient, dict[str, Any]]:
    """Require chain, pool bytecode, archive block, and one-block log support."""
    attempts: list[dict[str, Any]] = []
    eligible: list[str] = []
    first_probe_ts = base.utc_timestamp(base.PROBE_DATES[0])

    for endpoint in endpoints:
        rpc = BoundedFailoverRpcClient(
            [endpoint], max_calls=250, max_wall_seconds=180.0, per_endpoint_attempts=2
        )
        item: dict[str, Any] = {"endpoint": endpoint}
        try:
            chain_id = base.hex_int(rpc.call("eth_chainId", []))
            latest = base.hex_int(rpc.call("eth_blockNumber", []))
            code_sizes: dict[str, int] = {}
            for version, pool in pools.items():
                code = rpc.call("eth_getCode", [pool, "latest"])
                clean = code[2:] if isinstance(code, str) and code.startswith("0x") else ""
                code_sizes[version] = len(clean) // 2
            locator = base.BlockLocator(rpc, latest)
            historical_block = locator.first_at_or_after(first_probe_ts)
            for pool in pools.values():
                probe = rpc.call(
                    "eth_getLogs",
                    [
                        {
                            "fromBlock": hex(historical_block),
                            "toBlock": hex(historical_block),
                            "address": pool,
                            "topics": [base.EVENT_TOPIC],
                        }
                    ],
                )
                if not isinstance(probe, list):
                    raise EndpointUnavailable("single-block archive log probe was not a list")
            passed = chain_id == 1 and all(size > 0 for size in code_sizes.values())
            item.update(
                {
                    "status": "PASS" if passed else "FAIL",
                    "chain_id": chain_id,
                    "latest_block": latest,
                    "historical_probe_block": historical_block,
                    "pool_code_bytes": code_sizes,
                    "rpc_stats": vars(rpc.stats),
                }
            )
            if passed:
                eligible.append(endpoint)
        except Exception as exc:
            item.update(
                {"status": "ERROR", "error": repr(exc), "rpc_stats": vars(rpc.stats)}
            )
        attempts.append(item)

    if not eligible:
        raise EndpointUnavailable(
            json.dumps({"endpoint_attempts": attempts}, indent=2, sort_keys=True)
        )
    rpc = BoundedFailoverRpcClient(
        eligible, max_calls=3000, max_wall_seconds=1200.0, per_endpoint_attempts=2
    )
    return rpc, {
        "selected": eligible[0],
        "eligible_failover_endpoints": eligible,
        "attempts": attempts,
        "transport_contract": {
            "max_calls": rpc.max_calls,
            "max_wall_seconds": 1200.0,
            "per_endpoint_attempts": rpc.per_endpoint_attempts,
            "range_bisection_only_on_explicit_range_error": True,
        },
    }


def _output_path_from_argv() -> Path | None:
    try:
        index = sys.argv.index("--output")
        return Path(sys.argv[index + 1])
    except (ValueError, IndexError):
        return None


def main() -> int:
    base.choose_endpoint = choose_endpoint_bounded
    base.get_logs_adaptive = get_logs_bounded
    rc = int(base.main())
    output = _output_path_from_argv()
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        policy = {
            "schema_version": 1,
            "claim_id": "CLM-20260726-1952-ML-AAVE-LIQUIDATION-001",
            "source_transport_only": True,
            "market_price_opened": False,
            "model_opened": False,
            "pnl_opened": False,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
            "range_bisection_only_on_explicit_range_error": True,
            "max_calls": 3000,
            "max_wall_seconds": 1200,
            "per_endpoint_attempts": 2,
        }
        (output / "TRANSPORT_ATTESTATION.json").write_text(
            json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
