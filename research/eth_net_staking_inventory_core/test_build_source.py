from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_source.py")
SPEC = importlib.util.spec_from_file_location("build_source", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["build_source"] = MODULE
SPEC.loader.exec_module(MODULE)


def test_deposit_url_uses_public_daily_partition() -> None:
    assert MODULE.url_for(date(2023, 4, 12)).endswith(
        "/canonical_beacon_block_deposit/2023/4/12.parquet"
    )


def test_uint128_deposit_amount_decode() -> None:
    expected = 32_000_000_000
    raw = expected.to_bytes(16, byteorder="little", signed=False)
    assert MODULE.decode_integer(raw) == expected


def test_unix_slot_timestamp_decode() -> None:
    value = 1_681_338_503
    assert MODULE.decode_datetime(value) == datetime.fromtimestamp(value, tz=timezone.utc)


def test_text_normalization_handles_fixed_ascii_and_binary() -> None:
    assert MODULE.normalize_text(b"0xabc\x00\x00") == "0xabc"
    assert MODULE.normalize_text(bytes.fromhex("ab" * 4)) == "0x" + "ab" * 4


def test_source_delay_is_fixed() -> None:
    assert MODULE.SOURCE_DELAY_SECONDS == 180


def test_period_is_exact_pre2024_overlap() -> None:
    values = list(MODULE.days(MODULE.START, MODULE.END))
    assert len(values) == 264
    assert values[0] == date(2023, 4, 12)
    assert values[-1] == date(2023, 12, 31)
