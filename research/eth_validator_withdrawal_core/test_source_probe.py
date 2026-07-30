from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("source_probe.py")
SPEC = importlib.util.spec_from_file_location("source_probe", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["source_probe"] = MODULE
SPEC.loader.exec_module(MODULE)


def test_url_uses_unpadded_xatu_partition() -> None:
    assert MODULE.url_for(date(2023, 4, 12)).endswith("/2023/4/12.parquet")


def test_days_inclusive() -> None:
    values = list(MODULE.days(date(2023, 4, 12), date(2023, 4, 14)))
    assert values == [date(2023, 4, 12), date(2023, 4, 13), date(2023, 4, 14)]


def test_address_normalization_preserves_hex() -> None:
    address = "0x" + "ab" * 20
    assert MODULE.normalize_address(address) == address
    assert MODULE.ADDRESS_RE.match(address)


def test_contiguous_ranges() -> None:
    rows = [
        MODULE.Availability("2023-04-12", "u", 200, True, 1, 1, None),
        MODULE.Availability("2023-04-13", "u", 200, True, 1, 1, None),
        MODULE.Availability("2023-04-14", "u", 404, False, None, 1, "404"),
        MODULE.Availability("2023-04-15", "u", 404, False, None, 1, "404"),
        MODULE.Availability("2023-04-16", "u", 200, True, 1, 1, None),
    ]
    assert MODULE.contiguous_ranges(rows, available=True) == [
        ["2023-04-12", "2023-04-13"],
        ["2023-04-16", "2023-04-16"],
    ]
    assert MODULE.contiguous_ranges(rows, available=False) == [
        ["2023-04-14", "2023-04-15"]
    ]


def test_required_columns_are_source_only() -> None:
    assert "withdrawal_amount" in MODULE.REQUIRED_COLUMNS
    forbidden = {"price", "return", "pnl", "nav", "funding", "open_interest"}
    assert not (forbidden & MODULE.REQUIRED_COLUMNS)


def test_xatu_uint128_little_endian_decode() -> None:
    import pyarrow as pa

    expected = 4_500_000_000
    raw = expected.to_bytes(16, byteorder="little", signed=False)
    array = pa.chunked_array([pa.array([raw], type=pa.binary(16))])
    assert MODULE.integer_values(array) == [expected]


def test_xatu_unix_seconds_decode_is_utc() -> None:
    import pyarrow as pa

    value = 1_681_338_503
    array = pa.chunked_array([pa.array([value], type=pa.int64())])
    assert MODULE.datetime_values(array) == [
        datetime.fromtimestamp(value, tz=timezone.utc)
    ]
