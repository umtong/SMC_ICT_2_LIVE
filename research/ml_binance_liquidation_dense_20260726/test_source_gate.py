from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

import source_gate as sg


def make_zip(csv_text: str, name: str = "BTCUSDT-liquidationSnapshot-2022-01.csv") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, csv_text)
    return output.getvalue()


def test_headered_archive_parses_buy_sell_and_notional() -> None:
    header = ",".join(sg.EXPECTED_FIELDS)
    payload = make_zip(
        header
        + "\n"
        + "1640995200000,SELL,LIMIT,IOC,2,47000,46990,FILLED,2,2\n"
        + "1640995260000,BUY,LIMIT,IOC,1,47100,47110,FILLED,1,1\n"
    )
    rows = list(sg.iter_liquidation_rows(payload))
    assert [row["side"] for row in rows] == ["SELL", "BUY"]
    assert rows[0]["notional"] == pytest.approx(93980.0)
    assert rows[1]["notional"] == pytest.approx(47110.0)


def test_headerless_archive_does_not_materialize_or_skip_first_row() -> None:
    payload = make_zip(
        "1640995200000,SELL,LIMIT,IOC,2,47000,46990,FILLED,2,2\n"
        "1640995260000,BUY,LIMIT,IOC,1,47100,47110,FILLED,1,1\n"
    )
    rows = list(sg.iter_liquidation_rows(payload))
    assert len(rows) == 2
    assert rows[0]["time"] == 1640995200000
    assert rows[1]["time"] == 1640995260000


def test_microsecond_timestamp_normalizes_to_milliseconds() -> None:
    assert sg.parse_timestamp("1640995200000000") == 1640995200000
    assert sg.parse_timestamp("1640995200000") == 1640995200000


def test_nonfinite_and_negative_amounts_rejected() -> None:
    with pytest.raises(sg.SourceGateError):
        sg.parse_float("nan", "quantity")
    with pytest.raises(sg.SourceGateError):
        sg.parse_float("inf", "quantity")
    with pytest.raises(sg.SourceGateError):
        sg.parse_float("-1", "quantity")


def test_checksum_filename_and_value_are_enforced() -> None:
    digest = hashlib.sha256(b"abc").hexdigest()
    assert sg.parse_checksum(f"{digest}  file.zip\n".encode(), "file.zip") == digest
    with pytest.raises(sg.SourceGateError):
        sg.parse_checksum(f"{digest}  other.zip\n".encode(), "file.zip")


def test_fixed_chronology_helpers_cover_boundaries() -> None:
    assert sg.month_sequence("2021-11", "2022-02") == [
        "2021-11", "2021-12", "2022-01", "2022-02"
    ]
    days = sg.day_sequence("2021-12", "2022-01")
    assert days[0] == "2021-12-01"
    assert days[-1] == "2022-01-31"
    assert len(days) == 62


def test_expected_keys_and_periods_are_consistent() -> None:
    monthly = sg.expected_key("BTCUSDT", "monthly", "2022-01")
    daily = sg.expected_key("ETHUSDT", "daily", "2023-08-17")
    assert sg.period_from_key(monthly, "monthly") == "2022-01"
    assert sg.period_from_key(daily, "daily") == "2023-08-17"
    assert sg.period_from_key(monthly + ".CHECKSUM", "monthly") is None


def test_wrong_period_in_archive_is_rejected_by_inspector(monkeypatch, tmp_path) -> None:
    header = ",".join(sg.EXPECTED_FIELDS)
    payload = make_zip(
        header
        + "\n"
        + "1643673600000,SELL,LIMIT,IOC,2,47000,46990,FILLED,2,2\n",
        name="BTCUSDT-liquidationSnapshot-2022-01.csv",
    )
    digest = hashlib.sha256(payload).hexdigest().encode()
    calls = iter([digest + b"  BTCUSDT-liquidationSnapshot-2022-01.zip\n", payload])
    monkeypatch.setattr(sg, "request_bytes", lambda *args, **kwargs: next(calls))
    with pytest.raises(sg.SourceGateError, match="outside 2022-01"):
        with sg.gzip.open(tmp_path / "sample.gz", "wb") as handle:
            sg.inspect_archive(
                object(),
                key="data/futures/um/monthly/liquidationSnapshot/BTCUSDT/"
                    "BTCUSDT-liquidationSnapshot-2022-01.zip",
                expected_period="2022-01",
                layout="monthly",
                download_base="https://example.invalid",
                sample_output=handle,
                symbol="BTCUSDT",
            )
