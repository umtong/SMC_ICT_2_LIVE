from datetime import datetime, timezone

import pytest

from source_gate_authoritative import (
    CONTRACTS,
    FIXED_MONTHS,
    TRANSFER_TOPIC,
    ZERO_TOPIC,
    Event,
    decode_log,
    event_to_dict,
    first_block_at_or_after,
    month_bounds,
    normalize_address_topic,
)


def test_full_source_months_are_complete_and_pre_2024() -> None:
    assert len(FIXED_MONTHS) == 36
    assert FIXED_MONTHS[0] == "2021-01"
    assert FIXED_MONTHS[-1] == "2023-12"
    assert len(set(FIXED_MONTHS)) == len(FIXED_MONTHS)
    expected = tuple(
        f"{year}-{month:02d}"
        for year in (2021, 2022, 2023)
        for month in range(1, 13)
    )
    assert FIXED_MONTHS == expected


class FakeClient:
    def __init__(self, timestamps: dict[int, int]) -> None:
        self.timestamps = timestamps

    def call(self, method: str, params: list[object]) -> dict[str, str]:
        assert method == "eth_getBlockByNumber"
        number = int(str(params[0]), 16)
        return {"timestamp": hex(self.timestamps[number])}


def test_exact_2024_boundary_is_only_an_end_exclusive_lookup() -> None:
    boundary = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    # Block 100 is the first block at the end-exclusive 2024 boundary. The
    # authoritative eligibility boundary must be 64 blocks earlier so every
    # retained 2023 event can be observed under both the +12 and +64 block
    # availability contracts without reading a 2024 block.
    client = FakeClient(
        {i: boundary - (100 - i) * 12 for i in range(101)}
    )
    assert first_block_at_or_after(client, boundary, 0, 100, {}) == 36
    with pytest.raises(ValueError):
        first_block_at_or_after(client, boundary + 1, 0, 100, {})


def test_ordinary_historical_boundary_is_not_shifted() -> None:
    boundary = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    client = FakeClient(
        {i: boundary - (100 - i) * 12 for i in range(101)}
    )
    assert first_block_at_or_after(client, boundary - 120, 0, 100, {}) == 90


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
