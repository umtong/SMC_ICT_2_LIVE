from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_stablecoin_profit_v5_rpc_filter_authority as authority


def _load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("filtered_rpc_helper", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _materialized_helper(tmp_path: Path) -> Any:
    helper = tmp_path / "source_gate_eth_rpc_transport.py"
    source = ROOT / "scripts" / "stablecoin_eth_rpc_log_transport.py"
    helper.write_bytes(source.read_bytes())
    authority.prior.patch_rpc_helper(helper)
    authority.patch_rpc_filter_validation(helper)
    return _load_module(helper)


def test_correction_follows_durable_filter_mismatch_only() -> None:
    payload = authority._load_correction()
    observed = payload["observed_run"]
    assert observed["workflow_run"] == 30523666892
    assert observed["artifact_id"] == 8752764515
    assert observed["failure_message"] == "burn filter mismatch"
    assert observed["source_pass_fail_observed"] is False
    correction = payload["transport_correction"]
    assert correction["scientific_contract_changed"] is False
    assert correction["source_event_or_filter_changed"] is False
    assert correction["decoder_or_deduplication_changed"] is False


def test_filter_violating_provider_fails_over_before_decoder(tmp_path: Path) -> None:
    module = _materialized_helper(tmp_path)
    address = "0x" + "12" * 20
    transfer = "0x" + "ab" * 32
    zero = "0x" + "0" * 64
    nonzero = "0x" + "34" * 32
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getLogs",
        "params": [
            {
                "fromBlock": "0x10",
                "toBlock": "0x20",
                "address": address,
                "topics": [transfer, None, zero],
            }
        ],
    }

    class Fake(module.EthereumRpcLogMixin):
        rpc_endpoints = ("filter-violating", "working")

        def __init__(self) -> None:
            self.errors: list[str] = []

        def _rpc_post_to_endpoint(self, endpoint: str, payload: Any) -> Any:
            del payload
            if endpoint == "filter-violating":
                return {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": [
                        {
                            "address": address,
                            "topics": [transfer, nonzero, nonzero],
                            "data": "0x01",
                            "blockNumber": "0x10",
                            "transactionHash": "0x" + "cd" * 32,
                            "logIndex": "0x0",
                        }
                    ],
                }
            return {"jsonrpc": "2.0", "id": 1, "result": []}

    client = Fake()
    body, endpoint = client._rpc_request(request)
    assert endpoint == "working"
    assert body["result"] == []
    assert any("outside the exact eth_getLogs filter" in item for item in client.errors)


def test_all_filter_violating_providers_fail_closed(tmp_path: Path) -> None:
    module = _materialized_helper(tmp_path)
    address = "0x" + "12" * 20
    transfer = "0x" + "ab" * 32
    zero = "0x" + "0" * 64
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getLogs",
        "params": [{"address": address, "topics": [transfer, None, zero]}],
    }

    class Fake(module.EthereumRpcLogMixin):
        rpc_endpoints = ("wrong-a", "wrong-b")

        def __init__(self) -> None:
            self.errors: list[str] = []

        def _rpc_post_to_endpoint(self, endpoint: str, payload: Any) -> Any:
            del endpoint, payload
            return {
                "jsonrpc": "2.0",
                "id": 1,
                "result": [
                    {
                        "address": address,
                        "topics": [transfer, zero, "0x" + "56" * 32],
                        "blockNumber": "0x10",
                        "transactionHash": "0x" + "ef" * 32,
                        "logIndex": "0x0",
                    }
                ],
            }

    with pytest.raises(module.EthereumRpcTransportError, match="all public Ethereum RPC endpoints failed"):
        Fake()._rpc_request(request)


def test_exact_overlay_rejects_second_application(tmp_path: Path) -> None:
    helper = tmp_path / "source_gate_eth_rpc_transport.py"
    source = ROOT / "scripts" / "stablecoin_eth_rpc_log_transport.py"
    helper.write_bytes(source.read_bytes())
    authority.prior.patch_rpc_helper(helper)
    authority.patch_rpc_filter_validation(helper)
    with pytest.raises(RuntimeError):
        authority.patch_rpc_filter_validation(helper)
