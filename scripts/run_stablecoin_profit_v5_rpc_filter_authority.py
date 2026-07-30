from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import run_stablecoin_profit_v5_rpc_failover_authority as prior

ROOT = Path(__file__).resolve().parents[1]
CORRECTION_ID = (
    "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-"
    "EXACT-RPC-FILTER-RESPONSE-VALIDATION-017"
)
CORRECTION_PATH = (
    ROOT
    / "research"
    / "execution"
    / "stablecoin_profit_v5_20260727"
    / "EXECUTION_CORRECTION_017_EXACT_RPC_FILTER_RESPONSE_VALIDATION_AFTER_FAILURE.json"
)
_ORIGINAL_REPAIR = prior.repair_materialized_source_rpc_failover
_REQUEST_OLD = prior._REQUEST_NEW
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

    @staticmethod
    def _raise_rpc_filter_mismatch(payload: Any, body: Any) -> None:
        if not (
            isinstance(payload, dict)
            and payload.get("method") == "eth_getLogs"
        ):
            return
        params = payload.get("params")
        if not (
            isinstance(params, list)
            and len(params) == 1
            and isinstance(params[0], dict)
        ):
            raise EthereumRpcTransportError(
                "eth_getLogs request lacks one filter object"
            )
        requested = params[0]
        expected_address = str(requested.get("address", "")).lower()
        expected_topics = requested.get("topics")
        if not expected_address or not isinstance(expected_topics, list):
            raise EthereumRpcTransportError(
                "eth_getLogs request lacks frozen address/topics"
            )
        if not isinstance(body, dict) or not isinstance(body.get("result"), list):
            return
        for row in body["result"]:
            if not isinstance(row, dict):
                raise EthereumRpcTransportError(
                    "eth_getLogs returned a non-object row"
                )
            actual_address = str(row.get("address", "")).lower()
            actual_topics = row.get("topics")
            mismatch: dict[str, Any] | None = None
            if actual_address != expected_address:
                mismatch = {
                    "field": "address",
                    "expected": expected_address,
                    "observed": actual_address,
                }
            elif not isinstance(actual_topics, list):
                mismatch = {
                    "field": "topics",
                    "expected": expected_topics,
                    "observed": actual_topics,
                }
            else:
                for index, expected in enumerate(expected_topics):
                    if expected is None:
                        continue
                    observed = (
                        str(actual_topics[index]).lower()
                        if index < len(actual_topics)
                        else None
                    )
                    if observed != str(expected).lower():
                        mismatch = {
                            "field": f"topics[{index}]",
                            "expected": str(expected).lower(),
                            "observed": observed,
                        }
                        break
            if mismatch is not None:
                mismatch.update(
                    {
                        "blockNumber": row.get("blockNumber"),
                        "transactionHash": row.get("transactionHash"),
                        "logIndex": row.get("logIndex"),
                    }
                )
                raise EthereumRpcTransportError(
                    "provider returned a row outside the exact eth_getLogs filter: "
                    + json.dumps(mismatch, sort_keys=True)
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
                    self._raise_rpc_filter_mismatch(payload, body)
                except EthereumRpcTransportError as exc:
                    # Deterministic provider errors and filter-violating rows are
                    # provider failures. Try the next provider before splitting.
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
        raise AssertionError("exact RPC filter-response correction identity changed")
    if payload.get("claim_id") != prior.prior.prior.post.prior.REPAIR_CLAIM_ID:
        raise AssertionError("exact RPC filter-response correction claim changed")
    if payload.get("timing") != (
        "AFTER_DURABLE_TRANSPORT_RESPONSE_MISMATCH_BEFORE_ANY_SOURCE_PASS_FAIL_"
        "MARKET_ROW_LABEL_MODEL_TRADE_PNL_OR_OFFICIAL_INTERVAL"
    ):
        raise AssertionError("exact RPC filter-response correction timing changed")
    observed = payload.get("observed_run", {})
    if observed.get("workflow_run") != 30523666892:
        raise AssertionError("unexpected observed response-mismatch run")
    if observed.get("artifact_id") != 8752764515:
        raise AssertionError("unexpected observed response-mismatch artifact")
    if observed.get("failure_message") != "burn filter mismatch":
        raise AssertionError("unexpected observed response-mismatch message")
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
    if correction.get("decoder_or_deduplication_changed") is not False:
        raise AssertionError("decoder/deduplication changed")
    return payload


def patch_rpc_filter_validation(path: Path) -> Path:
    _load_correction()
    prior.prior.prior.post.prior._replace_exact(path, _REQUEST_OLD, _REQUEST_NEW)
    return path


def repair_materialized_source_rpc_filter(repository: Path) -> Path:
    repaired = _ORIGINAL_REPAIR(repository)
    helper = (
        repository
        / "research"
        / "ml_stablecoin_issuance_20260726"
        / "source_gate_eth_rpc_transport.py"
    )
    patch_rpc_filter_validation(helper)
    print(
        "STABLECOIN_V5_EXACT_RPC_FILTER_RESPONSE_VALIDATION_APPLIED",
        json.dumps(
            {
                "correction_id": CORRECTION_ID,
                "path": str(helper),
                "source_event_or_filter_changed": False,
                "scientific_contract_changed": False,
                "decoder_or_deduplication_changed": False,
                "provider_filter_mismatch_policy": "FAILOVER_THEN_FAIL_CLOSED",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return repaired


def main() -> int:
    _load_correction()
    original = prior.repair_materialized_source_rpc_failover
    prior.repair_materialized_source_rpc_failover = (
        repair_materialized_source_rpc_filter
    )
    try:
        return prior.main()
    finally:
        prior.repair_materialized_source_rpc_failover = original


if __name__ == "__main__":
    raise SystemExit(main())
