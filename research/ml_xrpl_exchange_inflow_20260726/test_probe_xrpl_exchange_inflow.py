from __future__ import annotations

import math

import pytest

from probe_xrpl_exchange_inflow import (
    PARTIAL_PAYMENT_FLAG,
    RIPPLE_EPOCH_UNIX,
    WALLETS,
    InflowEvent,
    marker_fingerprint,
    native_delivered_xrp,
    parse_inflow_event,
    qualified_events,
    ripple_date_to_ms,
)


def base_item(*, source: str = "rExternal", destination_tag: int | None = 77):
    wallet = dict(WALLETS[0])
    tx = {
        "Account": source,
        "Destination": wallet["account"],
        "TransactionType": "Payment",
        "Amount": "2500000",
    }
    if destination_tag is not None:
        tx["DestinationTag"] = destination_tag
    return wallet, {
        "validated": True,
        "ledger_index": 100,
        "hash": "ABC",
        "close_time_iso": "2023-01-01T00:01:00Z",
        "tx_json": tx,
        "meta": {
            "TransactionResult": "tesSUCCESS",
            "delivered_amount": "2500000",
        },
    }


def test_ripple_epoch_conversion() -> None:
    assert ripple_date_to_ms(0) == RIPPLE_EPOCH_UNIX * 1000


def test_marker_fingerprint_is_key_order_independent() -> None:
    assert marker_fingerprint({"ledger": 1, "seq": 2}) == marker_fingerprint(
        {"seq": 2, "ledger": 1}
    )


def test_parse_v2_native_xrp_payment() -> None:
    wallet, item = base_item()
    event = parse_inflow_event(item, wallet, result_validated=True)
    assert event.tx_hash == "ABC"
    assert event.exchange == "Binance"
    assert event.external is True
    assert event.tagged is True
    assert math.isclose(event.amount_xrp, 2.5)
    assert event.bin_start_ms % (15 * 60 * 1000) == 0


def test_internal_payment_is_not_primary() -> None:
    wallet, item = base_item(source=WALLETS[1]["account"])
    event = parse_inflow_event(item, wallet, result_validated=True)
    assert event.external is False
    assert qualified_events([event]) == []


def test_untagged_payment_is_not_primary() -> None:
    wallet, item = base_item(destination_tag=None)
    event = parse_inflow_event(item, wallet, result_validated=True)
    assert event.external is True
    assert event.tagged is False
    assert qualified_events([event]) == []


def test_issued_delivered_amount_is_rejected() -> None:
    tx = {"Amount": "1", "Flags": 0}
    meta = {
        "delivered_amount": {
            "currency": "USD",
            "issuer": "rIssuer",
            "value": "1",
        }
    }
    with pytest.raises(ValueError, match="not native XRP"):
        native_delivered_xrp(tx, meta)


def test_partial_payment_without_delivered_amount_is_rejected() -> None:
    tx = {"Amount": "2500000", "Flags": PARTIAL_PAYMENT_FLAG}
    with pytest.raises(ValueError, match="partial payment"):
        native_delivered_xrp(tx, {})


def test_failed_payment_is_rejected() -> None:
    wallet, item = base_item()
    item["meta"]["TransactionResult"] = "tecPATH_DRY"
    with pytest.raises(ValueError, match="did not succeed"):
        parse_inflow_event(item, wallet, result_validated=True)


def test_ripple_date_fallback() -> None:
    wallet, item = base_item()
    item.pop("close_time_iso")
    item["tx_json"]["date"] = 0
    event = parse_inflow_event(item, wallet, result_validated=True)
    assert event.timestamp_ms == RIPPLE_EPOCH_UNIX * 1000
