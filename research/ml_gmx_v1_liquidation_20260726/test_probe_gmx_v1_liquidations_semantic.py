from __future__ import annotations

import probe_gmx_v1_liquidations as base
import probe_gmx_v1_liquidations_semantic as corrected


def _address_word(value: str) -> bytes:
    return bytes.fromhex(base.normalize_address(value)[2:]).rjust(32, b"\x00")


def _log(is_long: bool) -> dict[str, object]:
    words = [
        bytes.fromhex("11" * 32),
        _address_word("0x1111111111111111111111111111111111111111"),
        _address_word("0x2222222222222222222222222222222222222222"),
        _address_word(base.INDEX_TOKENS["BTC"]),
        (1 if is_long else 0).to_bytes(32, "big"),
        (1_250 * 10**30).to_bytes(32, "big"),
        (125 * 10**30).to_bytes(32, "big"),
        (1).to_bytes(32, "big"),
        (-5 * 10**30).to_bytes(32, "big", signed=True),
        (29_500 * 10**30).to_bytes(32, "big"),
    ]
    return {
        "address": base.VAULT,
        "topics": [base.LIQUIDATE_POSITION_TOPIC],
        "data": "0x" + b"".join(words).hex(),
        "blockNumber": "0x64",
        "blockHash": "0x" + "22" * 32,
        "transactionHash": "0x" + ("33" if is_long else "44") * 32,
        "transactionIndex": "0x2",
        "logIndex": "0x3",
        "removed": False,
    }


def test_long_is_removed_exposure_not_asserted_sell_order() -> None:
    row = corrected.decode_liquidation_log(
        _log(True), block_timestamp=1_650_000_000, probe_window="test"
    )
    assert row["removed_trader_exposure"] == "LONG_REMOVED"
    assert int(row["signed_removed_exposure_raw_1e30"]) < 0
    assert row["external_market_order_direction_asserted"] is False
    assert "forced_flow_direction" not in row


def test_short_is_removed_exposure_not_asserted_buy_order() -> None:
    row = corrected.decode_liquidation_log(
        _log(False), block_timestamp=1_650_000_000, probe_window="test"
    )
    assert row["removed_trader_exposure"] == "SHORT_REMOVED"
    assert int(row["signed_removed_exposure_raw_1e30"]) > 0
    assert row["external_market_order_direction_asserted"] is False
    assert row["mark_price_semantics"].endswith("NOT_EXTERNAL_EXECUTABLE_FILL")


def test_source_is_explicitly_censored_to_state_one_event() -> None:
    row = corrected.decode_liquidation_log(
        _log(True), block_timestamp=1_650_000_000, probe_window="test"
    )
    assert row["source_censoring"] == "LIQUIDATION_STATE_1_ONLY"
    assert row["source_semantic_correction"] == corrected.SEMANTIC_CORRECTION_ID
