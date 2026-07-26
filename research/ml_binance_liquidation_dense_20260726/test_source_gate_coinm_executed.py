from __future__ import annotations

import io
import zipfile

import source_gate_coinm_executed as corrected


def make_zip(csv_text: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "BTCUSD_PERP-liquidationSnapshot-2022-01-01.csv", csv_text
        )
    return output.getvalue()


def test_original_quantity_never_becomes_executed_flow() -> None:
    header = ",".join(corrected.EXPECTED_FIELDS)
    payload = make_zip(
        header
        + "\n"
        + "1640995200000,SELL,LIMIT,IOC,99,47000,0,NEW,0,0\n"
    )
    rows = list(corrected.iter_published_executed_rows(payload))
    assert rows == []


def test_accumulated_fill_is_published_executed_contract_count() -> None:
    header = ",".join(corrected.EXPECTED_FIELDS)
    payload = make_zip(
        header
        + "\n"
        + "1640995200000,SELL,LIMIT,IOC,9,47000,46990,PARTIALLY_FILLED,2,4\n"
    )
    rows = list(corrected.iter_published_executed_rows(payload))
    assert len(rows) == 1
    assert rows[0]["effective_quantity"] == 4.0
    assert rows[0]["published_executed_contract_count"] == 4.0
    assert rows[0]["original_quantity"] == 9.0
    assert rows[0]["snapshot_is_complete_liquidation_ledger"] is False


def test_last_fill_is_used_only_when_accumulated_is_zero() -> None:
    assert corrected.executed_contract_count(
        {"accumulated_filled_quantity": 0.0, "last_filled_quantity": 3.0}
    ) == 3.0


def test_snapshot_semantics_prohibit_total_flow_inference() -> None:
    semantics = corrected.SNAPSHOT_SEMANTICS
    assert "lower-bound" in semantics["coverage"]
    assert "does not prove" in semantics["absence"]
    assert "contractSize" in semantics["notional"]
