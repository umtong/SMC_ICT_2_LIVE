from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_module():
    path = ROOT / "sqd_signed_swap_source.py"
    spec = importlib.util.spec_from_file_location("sqd_signed_swap_source", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encode_signed(value: int) -> bytes:
    return (value if value >= 0 else (1 << 256) + value).to_bytes(32, "big")


def swap_data(amount0: int, amount1: int, tick: int) -> str:
    tick_encoded = tick if tick >= 0 else (1 << 256) + tick
    payload = (
        encode_signed(amount0)
        + encode_signed(amount1)
        + (2**96).to_bytes(32, "big")
        + (123456).to_bytes(32, "big")
        + tick_encoded.to_bytes(32, "big")
    )
    return "0x" + payload.hex()


def test_swap_buy_and_sell_direction() -> None:
    module = load_module()
    buy = module.decode_swap(swap_data(2_000_000_000, -10**18, 200_000))
    sell = module.decode_swap(swap_data(-2_000_000_000, 10**18, 200_000))
    assert buy["amount0_raw"] > 0 and buy["amount1_raw"] < 0
    assert sell["amount0_raw"] < 0 and sell["amount1_raw"] > 0
    assert 1_000 < buy["price_usdc_per_weth"] < 10_000


def test_negative_tick_decoding() -> None:
    module = load_module()
    decoded = module.decode_swap(swap_data(1_000_000, -10**15, -10))
    assert decoded["tick"] == -10


def test_hourly_availability_delay_and_aggregation() -> None:
    module = load_module()
    acc = module.HourlyAccumulator()
    first = {
        "address": module.POOL,
        "transactionHash": "0x" + "11" * 32,
        "logIndex": 1,
        "topics": [module.SWAP_TOPIC, "0x1", "0x2"],
        "data": swap_data(2_000_000_000, -10**18, 200_000),
    }
    second = {
        "address": module.POOL,
        "transactionHash": "0x" + "22" * 32,
        "logIndex": 2,
        "topics": [module.SWAP_TOPIC, "0x1", "0x2"],
        "data": swap_data(-1_000_000_000, 5 * 10**17, 200_010),
    }
    timestamp = 1_700_000_123
    acc.add(block_number=18_500_000, timestamp=timestamp, log=first)
    acc.add(block_number=18_500_000, timestamp=timestamp + 10, log=second)
    rows = acc.finalized_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["available_time"] == timestamp - timestamp % 3600 + 7200
    assert row["swap_count"] == 2
    assert row["buy_count"] == 1
    assert row["sell_count"] == 1
    assert row["net_usdc"] == 1000.0
    assert row["gross_usdc"] == 3000.0
    assert row["unique_transaction_count"] == 2


def test_exact_pre2024_month_contract() -> None:
    module = load_module()
    assert module.EXPECTED_PRE2024_MONTHS[0] == "2021-07"
    assert module.EXPECTED_PRE2024_MONTHS[-1] == "2023-12"
    assert len(module.EXPECTED_PRE2024_MONTHS) == 30
