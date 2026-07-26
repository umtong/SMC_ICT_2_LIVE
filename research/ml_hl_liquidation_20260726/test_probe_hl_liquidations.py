from __future__ import annotations

import json

import probe_hl_liquidations as probe


def liquidation_event(account_value: str = "-5.0") -> dict:
    return {
        "time": "2025-10-06T00:00:00.100000000",
        "hash": "0xabc",
        "inner": {
            "LedgerUpdate": {
                "users": ["0xUSER"],
                "delta": {
                    "type": "liquidation",
                    "liquidatedNtlPos": "1000",
                    "accountValue": account_value,
                    "leverageType": "Cross",
                    "liquidatedPositions": [
                        {"coin": "ETH", "szi": "1.0"},
                        {"coin": "BTC", "szi": "-0.1"},
                    ],
                },
            }
        },
    }


def test_frozen_paths_have_six_hours_per_date_and_no_2026() -> None:
    paths = probe.candidate_paths()
    assert len(paths) == 36
    assert all("2026" not in path for path in paths)
    for date in probe.DATES:
        token = date.replace("-", "")
        matching = [path for path in paths if f"/{token}/" in path]
        assert len(matching) == 6


def test_negative_account_value_is_valid_and_flow_sign_is_mechanical() -> None:
    found = list(probe.iter_liquidation_deltas(liquidation_event()))
    assert len(found) == 1
    delta, users, event_hash, event_time = found[0]
    event, positions = probe.validate_liquidation(
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
    assert event["account_value"] == -5.0
    assert positions[0]["coin"] == "ETH"
    assert positions[0]["forced_flow_side"] == "SELL"
    assert positions[1]["coin"] == "BTC"
    assert positions[1]["forced_flow_side"] == "BUY"


def test_payload_wrapper_finds_explicit_liquidation() -> None:
    wrapped = {"payload": [liquidation_event()]}
    found = list(probe.iter_liquidation_deltas(wrapped))
    assert len(found) == 1
    assert found[0][0]["type"] == "liquidation"


def test_commit_pinned_parquet_query_is_frozen_to_exact_src_paths() -> None:
    metadata = {
        "siblings": [
            {"rfilename": "state/checkpoint.json"},
            {"rfilename": "data/universal.parquet", "size": 123},
        ]
    }
    siblings = probe.find_parquet_siblings(metadata)
    assert [item["rfilename"] for item in siblings] == [
        "data/universal.parquet"
    ]
    url = probe.revision_url("abc123def456", "data/universal.parquet")
    assert "abc123def456" in url
    coverage_sql, event_sql = probe.build_queries(
        [url], probe.candidate_paths()
    )
    assert "GROUP BY _src" in coverage_sql
    assert "trim(events) <> '[]'" in event_sql
    assert "misc_events_by_block/hourly/20251006/0.lz4" in event_sql


def test_parquet_event_row_parses_explicit_liquidation() -> None:
    row = (
        "2025-10-06 00:00:00.250",
        "2025-10-06 00:00:00.100",
        123,
        json.dumps([liquidation_event()]),
        "misc_events_by_block/hourly/20251006/0.lz4",
    )
    liquidations, malformed, row_error = probe.parse_event_row(row, 0)
    assert row_error is None
    assert malformed == []
    assert len(liquidations) == 1
    assert liquidations[0]["positions"][0]["forced_flow_side"] == "SELL"
