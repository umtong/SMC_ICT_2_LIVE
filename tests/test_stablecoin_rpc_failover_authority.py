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

import run_stablecoin_profit_v5_rpc_failover_authority as authority


def test_correction_follows_durable_transport_failure_only() -> None:
    payload = authority._load_correction()
    assert payload["observed_run"]["workflow_run"] == 30521782836
    assert payload["observed_run"]["artifact_id"] == 8751428002
    assert payload["observed_run"]["source_pass_fail_observed"] is False
    assert payload["transport_correction"]["scientific_contract_changed"] is False
    assert payload["transport_correction"]["source_event_or_filter_changed"] is False


def _load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("patched_rpc_helper", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failover_overlay_is_exact_and_json_rpc_errors_try_next_provider(
    tmp_path: Path,
) -> None:
    helper = tmp_path / "source_gate_eth_rpc_transport.py"
    source = ROOT / "scripts" / "stablecoin_eth_rpc_log_transport.py"
    helper.write_bytes(source.read_bytes())

    authority.patch_rpc_helper(helper)

    text = helper.read_text(encoding="utf-8")
    assert authority._ENDPOINTS_OLD not in text
    assert authority._ENDPOINTS_NEW in text
    assert authority._REQUEST_OLD not in text
    assert authority._REQUEST_NEW in text

    module = _load_module(helper)

    class Fake(module.EthereumRpcLogMixin):
        rpc_endpoints = ("limited", "working")

        def __init__(self) -> None:
            self.errors: list[str] = []

        def _rpc_post_to_endpoint(self, endpoint: str, payload: Any) -> Any:
            del payload
            if endpoint == "limited":
                return {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {
                        "code": -32602,
                        "message": "eth_getLogs is limited to 0 - 50 blocks range",
                    },
                }
            return {"jsonrpc": "2.0", "id": 1, "result": []}

    body, endpoint = Fake()._rpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []}
    )
    assert endpoint == "working"
    assert body["result"] == []

    with pytest.raises(RuntimeError, match="replacement already present"):
        authority.patch_rpc_helper(helper)
