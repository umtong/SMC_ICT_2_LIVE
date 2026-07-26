from __future__ import annotations

import hashlib
import math

import pytest

from probe_xrpl_dex import (
    Candle,
    find_identity,
    matching_book_change,
    parse_candles,
    parse_candle_row,
    token_md5,
)


def test_token_md5_contract() -> None:
    assert token_md5("rExample", "USD") == hashlib.md5(
        b"rExample_USD"
    ).hexdigest()


@pytest.mark.parametrize(
    "row, expected_timestamp",
    [
        ([1640995200000, 1, 2, 0.5, 1.5, 3], 1640995200000),
        (
            {
                "time": 1640995200,
                "o": "1",
                "h": "2",
                "l": "0.5",
                "c": "1.5",
                "v": "3",
            },
            1640995200000,
        ),
    ],
)
def test_parse_candle_row(row, expected_timestamp: int) -> None:
    candle = parse_candle_row(row)
    assert candle.timestamp_ms == expected_timestamp
    assert candle.volume == 3


def test_parse_nested_candles_prefers_largest_valid_list() -> None:
    payload = {
        "noise": [1, 2, 3],
        "data": {
            "rows": [
                [1640995200000, 1, 2, 0.5, 1.5, 3],
                [1640996100000, 1.5, 2.5, 1, 2, 4],
            ]
        },
    }
    candles, errors = parse_candles(payload)
    assert len(candles) == 2
    assert candles[0].timestamp_ms < candles[1].timestamp_ms
    assert len(errors) == 0


def test_invalid_candle_is_rejected() -> None:
    with pytest.raises(ValueError):
        Candle(1, 2, 1, 3, 2, 1).validate()


def test_find_identity_nested() -> None:
    assert find_identity(
        {"data": {"token": {"issuer": "rIssuer", "currency": "USD"}}},
        "rIssuer",
        "USD",
    )


def test_matching_book_change_converts_drops() -> None:
    result = {
        "ledger_index": 99,
        "ledger_time": 1,
        "changes": [
            {
                "currency_a": "XRP_drops",
                "currency_b": "rIssuer/USD",
                "volume_a": "3500000",
                "volume_b": "2.8",
                "close": "1250000",
            },
            {
                "currency_a": "XRP_drops",
                "currency_b": "rOther/USD",
                "volume_a": "1",
                "volume_b": "1",
                "close": "1",
            },
        ],
    }
    matches = matching_book_change(result, "rIssuer", "USD")
    assert len(matches) == 1
    assert math.isclose(matches[0]["xrp_volume"], 3.5)
    assert math.isclose(matches[0]["xrp_per_token_close"], 1.25)
