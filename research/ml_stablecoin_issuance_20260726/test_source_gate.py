from datetime import datetime, timezone

import pytest

from source_gate import (
    CONTRACTS,
    TRANSFER_TOPIC,
    ZERO_TOPIC,
    Event,
    decode_log,
    event_to_dict,
    month_bounds,
    normalize_address_topic,
)


def test_month_bounds_never_open_2024() -> None:
    start, end = month_bounds("2023-12")
    assert start == int(datetime(2023, 12, 1, tzinfo=timezone.utc).timestamp())
    assert end == int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    with pytest.raises(ValueError):
        month_bounds("2024-01")


def test_mint_decode_and_identity() -> None:
    recipient = "1234567890abcdef1234567890abcdef12345678"
    log = {
        "address": CONTRACTS["USDC"]["address"],
        "topics": [TRANSFER_TOPIC, ZERO_TOPIC, "0x" + "0" * 24 + recipient],
        "data": hex(50_000_000 * 10**6),
        "blockNumber": "0x10",
        "transactionHash": "0x" + "12" * 32,
        "logIndex": "0x3",
    }
    row = decode_log("USDC", "MINT", log)
    assert row["amount_usd"] == 50_000_000
    assert row["from_address"] == "0x" + "0" * 40
    assert row["to_address"] == "0x" + recipient
    event = Event(
        token="USDC",
        direction="MINT",
        contract=CONTRACTS["USDC"]["address"].lower(),
        block_number=16,
        tx_hash=log["transactionHash"],
        log_index=3,
        amount_raw=row["amount_raw"],
        amount_usd=row["amount_usd"],
        from_address=row["from_address"],
        to_address=row["to_address"],
        block_timestamp=1,
        available_block_12=28,
        available_timestamp_12=2,
        available_block_64=80,
        available_timestamp_64=3,
    )
    assert event_to_dict(event)["event_id"] == event.event_id


def test_burn_filter_rejects_nonzero_to() -> None:
    log = {
        "address": CONTRACTS["USDT"]["address"],
        "topics": [
            TRANSFER_TOPIC,
            "0x" + "0" * 24 + "11" * 20,
            "0x" + "0" * 24 + "22" * 20,
        ],
        "data": "0x1",
        "blockNumber": "0x10",
        "transactionHash": "0x" + "34" * 32,
        "logIndex": "0x0",
    }
    with pytest.raises(ValueError):
        decode_log("USDT", "BURN", log)


def test_normalize_address_topic() -> None:
    assert normalize_address_topic("0x" + "0" * 24 + "ab" * 20) == "0x" + "ab" * 20
