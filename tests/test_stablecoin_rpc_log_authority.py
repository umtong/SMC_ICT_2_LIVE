from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_stablecoin_profit_v5_rpc_log_authority as authority
import stablecoin_eth_rpc_log_transport as rpc


def test_correction_is_transport_only_and_outcome_sealed() -> None:
    payload = authority._load_correction()
    assert payload["observed_run"]["workflow_run"] == 30485219744
    assert payload["observed_run"]["source_pass_fail_observed"] is False
    assert payload["observed_run"]["market_archive_opened"] is False
    correction = payload["transport_correction"]
    assert correction["source_event_or_filter_changed"] is False
    assert correction["scientific_contract_changed"] is False
    assert correction["decoder_or_deduplication_changed"] is False


def test_topic_translation_preserves_null_slots() -> None:
    topic0 = "0x" + "11" * 32
    topic2 = "0x" + "22" * 32
    assert rpc.topics_from_legacy_params(
        {"topic0": topic0, "topic2": topic2, "topic0_2_opr": "and"}
    ) == [topic0, None, topic2]
    with pytest.raises(rpc.EthereumRpcTransportError):
        rpc.topics_from_legacy_params({})


def test_patch_is_exact_and_changes_only_transport_binding(tmp_path: Path) -> None:
    pinned = tmp_path / "run_pinned_snapshot_source.py"
    pinned.write_text(
        "before\n"
        + authority._IMPORT_OLD
        + "\nclass ExactBatchClient:\n    pass\n"
        + authority._CLASS_MARKER
        + "    return {}\n"
        + authority._ASSIGN_OLD
        + "after\n",
        encoding="utf-8",
    )
    helper = tmp_path / "source_gate_eth_rpc_transport.py"

    authority.patch_pinned_source(pinned, helper)

    text = pinned.read_text(encoding="utf-8")
    assert authority._IMPORT_NEW in text
    assert "class EthereumRpcLogClient" in text
    assert authority._ASSIGN_NEW in text
    assert helper.read_bytes() == authority.HELPER_SOURCE.read_bytes()
    with pytest.raises(RuntimeError, match="replacement already present"):
        authority.patch_pinned_source(pinned, helper)


class _FakeRpcClient(rpc.EthereumRpcLogMixin):
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.request_count = 0
        self.last_request_at = 0.0
        self.block_timestamp_cache: dict[int, int] = {}

    def _log_params(
        self,
        address: str,
        direction: str,
        start_block: int,
        end_block: int,
    ) -> dict[str, Any]:
        del address, start_block, end_block
        return {
            "topic0": "0x" + "aa" * 32,
            **(
                {"topic1": "0x" + "00" * 32, "topic0_1_opr": "and"}
                if direction == "MINT"
                else {"topic2": "0x" + "00" * 32, "topic0_2_opr": "and"}
            ),
        }

    def _rpc_request(self, payload: Any) -> tuple[Any, str]:
        if isinstance(payload, list):
            return (
                [
                    {
                        "jsonrpc": "2.0",
                        "id": item["id"],
                        "result": {
                            "number": item["params"][0],
                            "timestamp": hex(1_700_000_000 + item["id"]),
                        },
                    }
                    for item in payload
                ],
                "fake",
            )
        assert payload["method"] == "eth_getLogs"
        params = payload["params"][0]
        return (
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": [
                    {
                        "address": params["address"],
                        "topics": params["topics"],
                        "data": "0x01",
                        "blockNumber": "0x10",
                        "transactionHash": "0x" + "ab" * 32,
                        "logIndex": "0x2",
                    }
                ],
            },
            "fake",
        )


def test_rpc_logs_preserve_filter_and_add_exact_timestamp() -> None:
    client = _FakeRpcClient()
    diagnostics: list[dict[str, Any]] = []
    rows = client.logs("0x" + "12" * 20, "BURN", 16, 20, diagnostics)
    assert len(rows) == 1
    assert rows[0]["blockNumber"] == "0x10"
    assert rows[0]["timeStamp"] == hex(1_700_000_001)
    assert rows[0]["topics"][1] is None
    assert diagnostics == [
        {
            "from_block": 16,
            "to_block": 20,
            "status": "PASS",
            "log_count": 1,
            "provider": "fake",
            "method": "eth_getLogs",
        }
    ]


def test_successful_empty_is_empty_but_rpc_error_is_not() -> None:
    class Empty(_FakeRpcClient):
        def _rpc_request(self, payload: Any) -> tuple[Any, str]:
            if isinstance(payload, list):
                return super()._rpc_request(payload)
            return {"jsonrpc": "2.0", "id": 1, "result": []}, "fake"

    rows = Empty().logs("0x" + "12" * 20, "MINT", 1, 2, [])
    assert rows == []

    class Failed(_FakeRpcClient):
        def _rpc_request(self, payload: Any) -> tuple[Any, str]:
            del payload
            raise rpc.EthereumRpcTransportError("provider unavailable")

    with pytest.raises(rpc.EthereumRpcTransportError, match="provider unavailable"):
        Failed().logs("0x" + "12" * 20, "MINT", 1, 1, [])
