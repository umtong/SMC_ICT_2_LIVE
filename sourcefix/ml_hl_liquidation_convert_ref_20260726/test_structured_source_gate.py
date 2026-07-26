from __future__ import annotations

import run_structured_source_gate as structured


def test_structured_event_queries_use_list_count_not_trim() -> None:
    paths = ["misc_events_by_block/hourly/20251006/0.lz4"]
    coverage, events = structured.build_structured_queries(
        ["https://example.invalid/data.parquet"], paths
    )
    assert "list_count(events)" in coverage
    assert "list_count(events)" in events
    assert "trim(events)" not in coverage.lower()
    assert "trim(events)" not in events.lower()
    assert paths[0] in coverage
    assert paths[0] in events


def test_wrapper_installs_structured_query_builder() -> None:
    assert structured.fixed.engine.build_queries is structured.build_structured_queries
    correction = structured.fixed._load_correction(structured.CORRECTION_007)
    assert correction["correction_id"] == "CORRECTION-20260726-HL-STRUCTURED-EVENT-LIST-007"
    assert correction["market_outcome_opened_before_correction"] is False
