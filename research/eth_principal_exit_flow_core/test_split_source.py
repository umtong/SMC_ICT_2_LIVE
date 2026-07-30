from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pyarrow as pa

MODULE_PATH = Path(__file__).with_name("split_source.py")
SPEC = importlib.util.spec_from_file_location("split_source", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["split_source"] = MODULE
SPEC.loader.exec_module(MODULE)


def test_principal_threshold_is_protocol_scale_and_fixed() -> None:
    assert MODULE.PRINCIPAL_GWEI == 16_000_000_000


def test_uint128_little_endian_decode() -> None:
    expected = 32_123_456_789
    raw = expected.to_bytes(16, byteorder="little", signed=False)
    array = pa.chunked_array([pa.array([raw], type=pa.binary(16))])
    assert MODULE.integer_values(array) == [expected]


def test_unix_second_timestamp_decode() -> None:
    value = 1_681_338_503
    assert MODULE.decode_datetime(value) == datetime.fromtimestamp(value, tz=timezone.utc)


def test_validate_index_set_ignores_physical_row_order() -> None:
    assert MODULE.validate_index_set([3, 1, 2]) == (1, 3)


def test_stream_conservation() -> None:
    principal = MODULE.empty_stream()
    partial = MODULE.empty_stream()
    MODULE.add_stream(principal, 32_000_000_000, 1, "0x" + "11" * 20)
    MODULE.add_stream(partial, 2_000_000_000, 2, "0x" + "22" * 20)
    p = MODULE.stream_fields("principal", principal)
    r = MODULE.stream_fields("partial", partial)
    assert p["principal_event_count"] + r["partial_event_count"] == 2
    assert p["principal_amount_gwei"] + r["partial_amount_gwei"] == 34_000_000_000


def test_source_url_uses_unpadded_partitions() -> None:
    assert MODULE.url_for(date(2023, 4, 12)).endswith("/2023/4/12.parquet")


def test_fixed_hex_normalization() -> None:
    address = bytes.fromhex("ab" * 20)
    root = bytes.fromhex("cd" * 32)
    assert MODULE.normalize_fixed_hex(address, 20) == "0x" + "ab" * 20
    assert MODULE.normalize_fixed_hex(root, 32) == "0x" + "cd" * 32
