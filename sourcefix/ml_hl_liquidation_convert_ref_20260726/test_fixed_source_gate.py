from __future__ import annotations

import json

import run_fixed_source_gate as fixed


def ledger_liquidation(*, explicit_notional: str | None = None) -> dict:
    delta = {
        "type": "ledgerLiquidation",
        "accountValue": "-5.0",
        "leverageType": "Cross",
        "liquidatedPositions": [
            {"coin": "ETH", "szi": "1.0"},
            {"coin": "BTC", "szi": "-0.1"},
        ],
    }
    if explicit_notional is not None:
        delta["liquidatedNtlPos"] = explicit_notional
    return {
        "time": "2025-10-06T00:00:00.100000000",
        "hash": "0xabc",
        "inner": {"LedgerUpdate": {"users": ["0xUSER"], "delta": delta}},
    }


def test_documented_schema_without_notional_is_valid() -> None:
    found = list(fixed.iter_ledger_liquidation_deltas(ledger_liquidation()))
    assert len(found) == 1
    delta, users, event_hash, event_time = found[0]
    event, positions = fixed.validate_ledger_liquidation(
        delta,
        block_number=123,
        block_time="2025-10-06T00:00:00.100000",
        local_time="2025-10-06T00:00:00.250000",
        event_hash=event_hash,
        event_time=event_time,
        users=users,
        source_path="synthetic",
        event_ordinal=0,
        ledger_ordinal=0,
    )
    assert event["delta_type"] == "ledgerLiquidation"
    assert event["liquidated_notional"] is None
    assert event["liquidated_notional_source"] == "UNAVAILABLE_UNTIL_CAUSAL_PRICE_JOIN"
    assert positions[0]["forced_flow_side"] == "SELL"
    assert positions[1]["forced_flow_side"] == "BUY"


def test_optional_explicit_notional_is_preserved_not_required() -> None:
    delta, users, event_hash, event_time = next(
        fixed.iter_ledger_liquidation_deltas(ledger_liquidation(explicit_notional="1000.5"))
    )
    event, _ = fixed.validate_ledger_liquidation(
        delta,
        block_number=123,
        block_time="2025-10-06T00:00:00.100000",
        local_time="2025-10-06T00:00:00.250000",
        event_hash=event_hash,
        event_time=event_time,
        users=users,
        source_path="synthetic",
        event_ordinal=0,
        ledger_ordinal=0,
    )
    assert event["liquidated_notional"] == 1000.5
    assert event["liquidated_notional_source"] == "EXPLICIT_SOURCE_FIELD"


def test_legacy_fill_type_is_not_misclassified_as_account_event() -> None:
    payload = ledger_liquidation()
    payload["inner"]["LedgerUpdate"]["delta"]["type"] = "liquidation"
    assert list(fixed.iter_ledger_liquidation_deltas(payload)) == []


def test_patched_engine_parse_event_row_uses_documented_schema() -> None:
    row = (
        "2025-10-06 00:00:00.250",
        "2025-10-06 00:00:00.100",
        123,
        json.dumps([ledger_liquidation()]),
        "misc_events_by_block/hourly/20251006/0.lz4",
    )
    liquidations, malformed, row_error = fixed.engine.parse_event_row(row, 0)
    assert row_error is None
    assert malformed == []
    assert len(liquidations) == 1
    assert liquidations[0]["positions"][0]["coin"] == "ETH"
