from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

import source_gate_coinm as sg


def make_zip(csv_text: str, name: str = "BTCUSD_PERP-liquidationSnapshot-2022-01-01.csv") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, csv_text)
    return output.getvalue()


def test_frozen_coinm_scope_and_mapping() -> None:
    assert sg.SOURCE_SYMBOLS == ("BTCUSD_PERP", "ETHUSD_PERP")
    assert sg.BYBIT_SIGNAL_MAP["BTCUSD_PERP"] == "BTCUSDT"
    assert sg.BYBIT_SIGNAL_MAP["ETHUSD_PERP"] == "ETHUSDT"


def test_expected_key_is_coinm_daily() -> None:
    key = sg.expected_key("BTCUSD_PERP", "2022-01-01")
    assert key == (
        "data/futures/cm/daily/liquidationSnapshot/BTCUSD_PERP/"
        "BTCUSD_PERP-liquidationSnapshot-2022-01-01.zip"
    )
    assert sg.key_date(key, "BTCUSD_PERP") == "2022-01-01"
    assert sg.key_date(key, "ETHUSD_PERP") is None


def test_headered_archive_parses_buy_sell() -> None:
    header = ",".join(sg.EXPECTED_FIELDS)
    payload = make_zip(
        header
        + "\n"
        + "1640995200000,SELL,LIMIT,IOC,2,47000,46990,FILLED,2,2\n"
        + "1640995260000,BUY,LIMIT,IOC,1,47100,47110,FILLED,1,1\n"
    )
    rows = list(sg.iter_liquidation_rows(payload))
    assert [row["side"] for row in rows] == ["SELL", "BUY"]
    assert rows[0]["effective_price"] == 46990.0
    assert rows[1]["effective_quantity"] == 1.0


def test_headerless_archive_keeps_first_row() -> None:
    payload = make_zip(
        "1640995200000,SELL,LIMIT,IOC,2,47000,46990,FILLED,2,2\n"
        "1640995260000,BUY,LIMIT,IOC,1,47100,47110,FILLED,1,1\n"
    )
    rows = list(sg.iter_liquidation_rows(payload))
    assert len(rows) == 2
    assert rows[0]["time"] == 1640995200000


def test_timestamp_normalization() -> None:
    assert sg.parse_timestamp("1640995200000000") == 1640995200000
    assert sg.parse_timestamp("1640995200000") == 1640995200000


def test_invalid_amounts_are_rejected() -> None:
    with pytest.raises(sg.SourceGateError):
        sg.parse_float("nan", "quantity")
    with pytest.raises(sg.SourceGateError):
        sg.parse_float("-1", "quantity")
    with pytest.raises(sg.SourceGateError):
        sg.parse_float("0", "quantity", allow_zero=False)


def test_checksum_filename_and_digest() -> None:
    digest = hashlib.sha256(b"abc").hexdigest()
    assert sg.parse_checksum(f"{digest}  file.zip\n".encode(), "file.zip") == digest
    with pytest.raises(sg.SourceGateError):
        sg.parse_checksum(f"{digest}  other.zip\n".encode(), "file.zip")


def test_date_sequence_is_complete_pre2024() -> None:
    dates = sg.date_sequence()
    assert dates[0] == "2021-01-01"
    assert dates[-1] == "2023-12-31"
    assert len(dates) == 1095
