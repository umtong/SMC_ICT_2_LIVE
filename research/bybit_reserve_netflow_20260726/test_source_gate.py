from __future__ import annotations

from source_gate import (
    BYBIT_ADDRESSES,
    TOKENS,
    TRANSFER_TOPIC,
    address_topic,
    canonical_rows_hash,
    choose_verification_range,
    decode_transfer,
    normalize_address,
)


def make_log(from_address: str, to_address: str, tx_byte: str = "aa") -> dict:
    return {
        "address": TOKENS["USDC"]["address"],
        "topics": [TRANSFER_TOPIC, address_topic(from_address), address_topic(to_address)],
        "data": hex(1_250_000 * 10**6),
        "blockNumber": hex(1_000),
        "transactionHash": "0x" + tx_byte * 32,
        "logIndex": hex(7),
    }


def test_address_round_trip() -> None:
    assert normalize_address(address_topic(BYBIT_ADDRESSES[0])) == BYBIT_ADDRESSES[0]


def test_inflow_outflow_and_internal_exclusion() -> None:
    outside = "0x" + "12" * 20
    inflow = decode_transfer("USDC", make_log(outside, BYBIT_ADDRESSES[0]))
    assert inflow is not None and inflow["direction"] == "INFLOW"
    outflow = decode_transfer("USDC", make_log(BYBIT_ADDRESSES[0], outside, "bb"))
    assert outflow is not None and outflow["direction"] == "OUTFLOW"
    assert decode_transfer("USDC", make_log(BYBIT_ADDRESSES[0], BYBIT_ADDRESSES[1], "cc")) is None


def test_canonical_hash_order_invariance() -> None:
    outside = "0x" + "34" * 20
    a = decode_transfer("USDC", make_log(outside, BYBIT_ADDRESSES[0], "aa"))
    b = decode_transfer("USDC", make_log(BYBIT_ADDRESSES[0], outside, "bb"))
    assert a is not None and b is not None
    assert canonical_rows_hash([a, b]) == canonical_rows_hash([b, a])


def test_verification_range_contains_anchor() -> None:
    rows = [{"block_number": 4_000}, {"block_number": 4_500}, {"block_number": 5_000}]
    start, end = choose_verification_range(rows, 1_000, 10_000)
    assert start <= 4_500 <= end
