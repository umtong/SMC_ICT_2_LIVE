from datetime import datetime, timezone

import pytest

from source_gate_authoritative import (
    CONTRACTS,
    FIXED_MONTHS,
    ISSUE_TOPIC,
    REDEEM_TOPIC,
    TRANSFER_TOPIC,
    ZERO_ADDRESS,
    ZERO_TOPIC,
    Event,
    decode_log,
    event_filter_topics,
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
    client = FakeClient({i: boundary - (100 - i) * 12 for i in range(101)})
    assert first_block_at_or_after(client, boundary, 0, 100, {}) == 36
    with pytest.raises(ValueError):
        first_block_at_or_after(client, boundary + 1, 0, 100, {})


def test_ordinary_historical_boundary_is_not_shifted() -> None:
    boundary = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    client = FakeClient({i: boundary - (100 - i) * 12 for i in range(101)})
    assert first_block_at_or_after(client, boundary - 120, 0, 100, {}) == 90


def test_month_bounds_never_open_2024() -> None:
    start, end = month_bounds("2023-12")
    assert start == int(datetime(2023, 12, 1, tzinfo=timezone.utc).timestamp())
    assert end == int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    with pytest.raises(ValueError):
        month_bounds("2024-01")


def test_usdc_zero_address_transfer_mint_decode_and_identity() -> None:
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
    assert row["from_address"] == ZERO_ADDRESS
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


def test_usdt_issue_and_redeem_are_canonical_supply_events() -> None:
    issue = {
        "address": CONTRACTS["USDT"]["address"],
        "topics": [ISSUE_TOPIC],
        "data": hex(75_000_000 * 10**6),
        "blockNumber": "0x20",
        "transactionHash": "0x" + "56" * 32,
        "logIndex": "0x1",
    }
    mint = decode_log("USDT", "MINT", issue)
    assert mint["amount_usd"] == 75_000_000
    assert mint["from_address"] == ZERO_ADDRESS
    assert mint["to_address"] == CONTRACTS["USDT"]["address"].lower()

    padded_issue = dict(issue)
    padded_issue["topics"] = [ISSUE_TOPIC, None, "", "0x"]
    padded_mint = decode_log("USDT", "MINT", padded_issue)
    assert padded_mint["amount_usd"] == 75_000_000

    redeem = dict(issue)
    redeem["topics"] = [REDEEM_TOPIC]
    redeem["transactionHash"] = "0x" + "78" * 32
    burn = decode_log("USDT", "BURN", redeem)
    assert burn["amount_usd"] == 75_000_000
    assert burn["from_address"] == CONTRACTS["USDT"]["address"].lower()
    assert burn["to_address"] == ZERO_ADDRESS

    assert event_filter_topics("USDT", "MINT") == [ISSUE_TOPIC]
    assert event_filter_topics("USDT", "BURN") == [REDEEM_TOPIC]


def test_ordinary_usdt_transfer_is_not_supply_issuance() -> None:
    ordinary = {
        "address": CONTRACTS["USDT"]["address"],
        "topics": [
            TRANSFER_TOPIC,
            ZERO_TOPIC,
            "0x" + "0" * 24 + "22" * 20,
        ],
        "data": hex(1_000_000 * 10**6),
        "blockNumber": "0x10",
        "transactionHash": "0x" + "34" * 32,
        "logIndex": "0x0",
    }
    with pytest.raises(ValueError):
        decode_log("USDT", "MINT", ordinary)


def test_usdc_burn_filter_rejects_nonzero_to() -> None:
    log = {
        "address": CONTRACTS["USDC"]["address"],
        "topics": [
            TRANSFER_TOPIC,
            "0x" + "0" * 24 + "11" * 20,
            "0x" + "0" * 24 + "22" * 20,
        ],
        "data": "0x1",
        "blockNumber": "0x10",
        "transactionHash": "0x" + "90" * 32,
        "logIndex": "0x0",
    }
    with pytest.raises(ValueError):
        decode_log("USDC", "BURN", log)


def test_usdt_supply_event_rejects_genuine_extra_topic_and_zero_amount() -> None:
    extra_topic = {
        "address": CONTRACTS["USDT"]["address"],
        "topics": [ISSUE_TOPIC, ZERO_TOPIC],
        "data": "0x1",
        "blockNumber": "0x10",
        "transactionHash": "0x" + "aa" * 32,
        "logIndex": "0x0",
    }
    with pytest.raises(ValueError):
        decode_log("USDT", "MINT", extra_topic)
    zero_amount = dict(extra_topic)
    zero_amount["topics"] = [ISSUE_TOPIC]
    zero_amount["data"] = "0x0"
    with pytest.raises(ValueError):
        decode_log("USDT", "MINT", zero_amount)


def test_normalize_address_topic() -> None:
    assert normalize_address_topic("0x" + "0" * 24 + "ab" * 20) == "0x" + "ab" * 20
