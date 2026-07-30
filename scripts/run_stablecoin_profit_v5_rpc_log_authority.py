from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import run_stablecoin_profit_v5_transport_window_authority as prior

ROOT = Path(__file__).resolve().parents[1]
CORRECTION_ID = (
    "EXECUTION-CORRECTION-20260730-STABLECOIN-V5-"
    "PUBLIC-ETH-RPC-LOG-TRANSPORT-015"
)
CORRECTION_PATH = (
    ROOT
    / "research"
    / "execution"
    / "stablecoin_profit_v5_20260727"
    / "EXECUTION_CORRECTION_015_PUBLIC_ETH_RPC_LOG_TRANSPORT_AFTER_FAILURE.json"
)
HELPER_SOURCE = ROOT / "scripts" / "stablecoin_eth_rpc_log_transport.py"

_IMPORT_OLD = "import source_gate_blockscout_authoritative as authority\n"
_IMPORT_NEW = (
    "import source_gate_blockscout_authoritative as authority\n"
    "import source_gate_eth_rpc_transport as rpc_transport\n"
)
_CLASS_MARKER = "\ndef _load_correction() -> dict[str, Any]:\n"
_CLASS_INSERT = """
class EthereumRpcLogClient(rpc_transport.EthereumRpcLogMixin, ExactBatchClient):
    \"\"\"Frozen decoder and filters with provider-independent log transport.\"\"\"


def _load_correction() -> dict[str, Any]:
"""
_ASSIGN_OLD = "    source.BlockscoutClient = ExactBatchClient\n"
_ASSIGN_NEW = "    source.BlockscoutClient = EthereumRpcLogClient\n"


def _load_correction() -> dict[str, Any]:
    payload = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    if payload.get("correction_id") != CORRECTION_ID:
        raise AssertionError("public Ethereum RPC correction identity changed")
    if payload.get("claim_id") != prior.post.prior.REPAIR_CLAIM_ID:
        raise AssertionError("public Ethereum RPC correction claim changed")
    if payload.get("timing") != (
        "AFTER_DURABLE_TRANSPORT_FAILURE_BEFORE_ANY_SOURCE_PASS_FAIL_"
        "MARKET_ROW_LABEL_MODEL_TRADE_PNL_OR_OFFICIAL_INTERVAL"
    ):
        raise AssertionError("public Ethereum RPC correction timing changed")
    observed = payload.get("observed_run", {})
    if observed.get("workflow_run") != 30485219744:
        raise AssertionError("unexpected durable transport-failure authority")
    if observed.get("status") != "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE":
        raise AssertionError("correction does not follow the durable source failure")
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


def patch_pinned_source(path: Path, helper_destination: Path) -> Path:
    _load_correction()
    if not HELPER_SOURCE.is_file():
        raise FileNotFoundError(HELPER_SOURCE)
    helper_destination.write_bytes(HELPER_SOURCE.read_bytes())
    prior.post.prior._replace_exact(path, _IMPORT_OLD, _IMPORT_NEW)
    prior.post.prior._replace_exact(path, _CLASS_MARKER, _CLASS_INSERT)
    prior.post.prior._replace_exact(path, _ASSIGN_OLD, _ASSIGN_NEW)
    return path


def repair_materialized_source_rpc_transport(repository: Path) -> Path:
    path = prior.repair_materialized_source_transport(repository)
    source_root = repository / "research" / "ml_stablecoin_issuance_20260726"
    repaired = patch_pinned_source(
        source_root / "run_pinned_snapshot_source.py",
        source_root / "source_gate_eth_rpc_transport.py",
    )
    print(
        "STABLECOIN_V5_PUBLIC_ETH_RPC_LOG_TRANSPORT_APPLIED",
        json.dumps(
            {
                "correction_id": CORRECTION_ID,
                "path": str(repaired),
                "helper": str(source_root / "source_gate_eth_rpc_transport.py"),
                "source_event_or_filter_changed": False,
                "scientific_contract_changed": False,
                "decoder_or_deduplication_changed": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return repaired


def main() -> int:
    _load_correction()
    original = prior.post.prior.repair_materialized_source_prefetch
    prior.post.prior.repair_materialized_source_prefetch = (
        repair_materialized_source_rpc_transport
    )
    try:
        return prior.post.main()
    finally:
        prior.post.prior.repair_materialized_source_prefetch = original


if __name__ == "__main__":
    raise SystemExit(main())
