from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("probe_gmx_v1_liquidations.py")
SPEC = importlib.util.spec_from_file_location("gmx_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def word_uint(value: int) -> bytes:
    return int(value).to_bytes(32, "big", signed=False)


def word_int(value: int) -> bytes:
    return int(value).to_bytes(32, "big", signed=True)


def word_address(value: str) -> bytes:
    return bytes.fromhex(probe.normalize_address(value)[2:]).rjust(32, b"\x00")


def synthetic_log(*, is_long: bool = True, realised_pnl: int = -5 * 10**30):
    words = [
        bytes.fromhex("11" * 32),
        word_address("0x1111111111111111111111111111111111111111"),
        word_address("0x2222222222222222222222222222222222222222"),
        word_address(probe.INDEX_TOKENS["BTC"]),
        word_uint(1 if is_long else 0),
        word_uint(1_250 * 10**30),
        word_uint(125 * 10**30),
        word_uint(987654321),
        word_int(realised_pnl),
        word_uint(29_500 * 10**30),
    ]
    return {
        "address": probe.VAULT,
        "topics": [probe.LIQUIDATE_POSITION_TOPIC],
        "data": "0x" + b"".join(words).hex(),
        "blockNumber": "0x64",
        "blockHash": "0x" + "22" * 32,
        "transactionHash": "0x" + "33" * 32,
        "transactionIndex": "0x2",
        "logIndex": "0x3",
        "removed": False,
    }


def test_frozen_source_identity() -> None:
    assert probe.CHAIN_ID == 42161
    assert probe.VAULT == "0x489ee077994b6658eafa855c308275ead8097c4a"
    assert probe.LIQUIDATE_POSITION_TOPIC == (
        "0x2e1f85a64a2f22cf2f0c42584e7c919ed4abe8d53675cff0f62bf1e95a1c676f"
    )
    assert all(
        probe.parse_utc(end) < probe.parse_utc("2024-01-01T00:00:00Z")
        for _, end in probe.PROBE_WINDOWS
    )


def test_decode_long_liquidation() -> None:
    row = probe.decode_liquidation_log(
        synthetic_log(is_long=True),
        block_timestamp=1_650_000_000,
        probe_window="frozen",
    )
    assert row["asset"] == "BTC"
    assert row["liquidated_position_side"] == "LONG"
    assert row["forced_flow_direction"] == "SELL"
    assert row["size_usd"] == "1250"
    assert row["collateral_usd"] == "125"
    assert row["realised_pnl_usd"] == "-5"
    assert row["mark_price_usd"] == "29500"
    assert row["causal_available_timestamp"] == 1_650_000_120
    assert row["transaction_index"] == 2
    assert row["log_index"] == 3


def test_decode_short_liquidation() -> None:
    row = probe.decode_liquidation_log(
        synthetic_log(is_long=False, realised_pnl=7 * 10**30),
        block_timestamp=1_650_000_000,
        probe_window="frozen",
    )
    assert row["liquidated_position_side"] == "SHORT"
    assert row["forced_flow_direction"] == "BUY"
    assert row["realised_pnl_usd"] == "7"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda log: log.update(
            {"address": "0x0000000000000000000000000000000000000001"}
        ),
        lambda log: log.update({"topics": []}),
        lambda log: log.update({"topics": ["0x" + "00" * 32]}),
        lambda log: log.update({"data": "0x00"}),
    ],
)
def test_rejects_malformed_log(mutator) -> None:
    log = synthetic_log()
    mutator(log)
    with pytest.raises(ValueError):
        probe.decode_liquidation_log(
            log,
            block_timestamp=1_650_000_000,
            probe_window="frozen",
        )


def test_rejects_noncanonical_bool() -> None:
    log = synthetic_log()
    raw = bytearray.fromhex(log["data"][2:])
    raw[4 * 32 : 5 * 32] = word_uint(2)
    log["data"] = "0x" + bytes(raw).hex()
    with pytest.raises(ValueError, match="bool"):
        probe.decode_liquidation_log(
            log,
            block_timestamp=1_650_000_000,
            probe_window="frozen",
        )


def test_range_error_classifier() -> None:
    assert probe.is_range_error(RuntimeError("query returned more than 10000 results"))
    assert probe.is_range_error(RuntimeError("maximum block range is 10000"))
    assert not probe.is_range_error(RuntimeError("HTTP 503: temporarily unavailable"))


def test_gate_requires_breadth_and_both_sides() -> None:
    result = {
        "endpoint_probe": {"selected": "example"},
        "decode_errors": [],
        "window_summaries": {
            f"w{i}": {"btc_eth_logs": 4 if i < 5 else 0} for i in range(6)
        },
    }
    records = []
    for i in range(20):
        log = synthetic_log(is_long=(i % 2 == 0))
        log["blockHash"] = "0x" + f"{i + 1:064x}"
        log["transactionHash"] = "0x" + f"{i + 101:064x}"
        row = probe.decode_liquidation_log(
            log,
            block_timestamp=1_650_000_000 + i,
            probe_window=f"w{i % 5}",
        )
        if i >= 10:
            row["index_token"] = probe.INDEX_TOKENS["ETH"]
            row["asset"] = "ETH"
        records.append(row)
    checks = probe.evaluate_gate(result, records)
    assert all(checks.values())
