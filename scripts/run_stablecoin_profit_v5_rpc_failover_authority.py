from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import run_stablecoin_profit_v5_rpc_log_authority as prior

ROOT = Path(__file__).resolve().parents[1]
CORRECTION_ID = (
    "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-"
    "ERROR-AWARE-MULTI-RPC-FAILOVER-016"
)
CORRECTION_PATH = (
    ROOT
    / "research"
    / "execution"
    / "stablecoin_profit_v5_20260727"
    / "EXECUTION_CORRECTION_016_ERROR_AWARE_MULTI_RPC_FAILOVER_AFTER_TRANSPORT_FAILURE.json"
)

_ENDPOINTS_OLD = '''RPC_ENDPOINTS = (
    "https://ethereum-rpc.publicnode.com",
    "https://public.1rpc.io/eth",
)
'''
_ENDPOINTS_NEW = '''RPC_ENDPOINTS = (
    "https://eth.blockscout.com/api/eth-rpc",
    "https://eth.drpc.org",
    "https://rpcfree.com/ethereum-rpc",
    "https://rpc.yearn.fi/chain/1",
    "https://rpc.nodeflare.app/eth/public",
    "https://ethereum-rpc.publicnode.com",
)
'''

_REQUEST_OLD = '''    def _rpc_request(self, payload: Any) -> tuple[Any, str]:
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
'''

_REQUEST_NEW = '''    @staticmethod
    def _raise_rpc_body_error(body: Any) -> None:
        if isinstance(body, dict) and body.get("error") is not None:
            raise EthereumRpcTransportError(
                json.dumps(body["error"], sort_keys=True)
            )
        if isinstance(body, list):
            failures = [
                item.get("error")
                for item in body
                if isinstance(item, dict) and item.get("error") is not None
            ]
            if failures:
                raise EthereumRpcTransportError(
                    json.dumps(failures[0], sort_keys=True)
                )

    def _rpc_request(self, payload: Any) -> tuple[Any, str]:
        errors: list[str] = []
        for endpoint in self.rpc_endpoints:
            for attempt in range(RPC_RETRIES_PER_ENDPOINT):
                try:
                    body = self._rpc_post_to_endpoint(endpoint, payload)
                except Exception as exc:
                    message = f"{endpoint}: {type(exc).__name__}: {exc}"
                    errors.append(message)
                    getattr(self, "errors", []).append(message)
                    if attempt + 1 < RPC_RETRIES_PER_ENDPOINT:
                        time.sleep(min(8.0, 1.5 * (2**attempt)))
                    continue
                try:
                    self._raise_rpc_body_error(body)
                except EthereumRpcTransportError as exc:
                    # A valid JSON-RPC error is deterministic for this endpoint
                    # and request. Move to the next provider instead of retrying it.
                    message = f"{endpoint}: {type(exc).__name__}: {exc}"
                    errors.append(message)
                    getattr(self, "errors", []).append(message)
                    break
                return body, endpoint
        raise EthereumRpcTransportError(
            "all public Ethereum RPC endpoints failed: " + " | ".join(errors[-12:])
        )
'''


def _load_correction() -> dict[str, Any]:
    payload = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    if payload.get("correction_id") != CORRECTION_ID:
        raise AssertionError("multi-RPC correction identity changed")
    if payload.get("claim_id") != prior.prior.post.prior.REPAIR_CLAIM_ID:
        raise AssertionError("multi-RPC correction claim changed")
    if payload.get("timing") != (
        "AFTER_DURABLE_TRANSPORT_FAILURE_BEFORE_ANY_SOURCE_PASS_FAIL_"
        "MARKET_ROW_LABEL_MODEL_TRADE_PNL_OR_OFFICIAL_INTERVAL"
    ):
        raise AssertionError("multi-RPC correction timing changed")
    observed = payload.get("observed_run", {})
    if observed.get("workflow_run") != 30521782836:
        raise AssertionError("unexpected observed transport failure")
    if observed.get("artifact_id") != 8751428002:
        raise AssertionError("unexpected observed failure artifact")
    if observed.get("status") != "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE":
        raise AssertionError("correction does not follow source transport failure")
    for key in (
        "source_pass_fail_observed",
        "market_archive_opened",
        "label_computed",
        "model_fitted",
        "trade_or_pnl_opened",
        "official_2024_2026_opened",
        "credentials_used",
        "orders_submitted",
    ):
        if observed.get(key) is not False:
            raise AssertionError(f"outcome seal failed: {key}")
    correction = payload.get("transport_correction", {})
    if correction.get("scientific_contract_changed") is not False:
        raise AssertionError("scientific contract changed")
    if correction.get("source_event_or_filter_changed") is not False:
        raise AssertionError("source event/filter changed")
    return payload


def patch_rpc_helper(path: Path) -> Path:
    _load_correction()
    prior.prior.post.prior._replace_exact(path, _ENDPOINTS_OLD, _ENDPOINTS_NEW)
    prior.prior.post.prior._replace_exact(path, _REQUEST_OLD, _REQUEST_NEW)
    return path


def repair_materialized_source_rpc_failover(repository: Path) -> Path:
    repaired = prior.repair_materialized_source_rpc_transport(repository)
    helper = (
        repository
        / "research"
        / "ml_stablecoin_issuance_20260726"
        / "source_gate_eth_rpc_transport.py"
    )
    patch_rpc_helper(helper)
    print(
        "STABLECOIN_V5_ERROR_AWARE_MULTI_RPC_FAILOVER_APPLIED",
        json.dumps(
            {
                "correction_id": CORRECTION_ID,
                "path": str(helper),
                "source_event_or_filter_changed": False,
                "scientific_contract_changed": False,
                "successful_empty_policy_changed": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return repaired


def main() -> int:
    _load_correction()
    original = prior.prior.post.prior.repair_materialized_source_prefetch
    prior.prior.post.prior.repair_materialized_source_prefetch = (
        repair_materialized_source_rpc_failover
    )
    try:
        return prior.prior.post.main()
    finally:
        prior.prior.post.prior.repair_materialized_source_prefetch = original


if __name__ == "__main__":
    raise SystemExit(main())
