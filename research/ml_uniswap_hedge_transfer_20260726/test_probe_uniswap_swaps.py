from __future__ import annotations

import probe_uniswap_swaps as probe


def topic_address(address: str) -> str:
    return "0x" + address.removeprefix("0x").rjust(64, "0")


def synthetic_log() -> dict:
    sender = "0x1111111111111111111111111111111111111111"
    recipient = "0x2222222222222222222222222222222222222222"
    data = b"".join(
        [
            probe.abi_signed_word(1_500_000_000),
            probe.abi_signed_word(-700_000_000_000_000_000),
            probe.abi_uint_word(2**96),
            probe.abi_uint_word(10**18),
            probe.abi_signed_word(-12345, 24),
        ]
    )
    return {
        "address": "0x3333333333333333333333333333333333333333",
        "topics": [probe.SWAP_TOPIC, topic_address(sender), topic_address(recipient)],
        "data": "0x" + data.hex(),
        "blockNumber": hex(12_345_678),
        "blockHash": "0x" + "ab" * 32,
        "transactionHash": "0x" + "cd" * 32,
        "transactionIndex": "0x2",
        "logIndex": "0x4",
        "removed": False,
    }


def test_official_swap_topic_is_frozen():
    assert probe.SWAP_TOPIC == "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"


def test_get_pool_calldata_is_selector_plus_three_words():
    data = probe.get_pool_calldata(probe.TOKENS["WETH"], probe.TOKENS["USDC"], 500)
    assert data.startswith("0x" + probe.GET_POOL_SELECTOR.hex())
    assert len(bytes.fromhex(data[2:])) == 4 + 32 * 3


def test_decode_swap_log_round_trip():
    row = probe.decode_swap_log(
        synthetic_log(),
        pool_name="TEST",
        expected_pool="0x3333333333333333333333333333333333333333",
        token0=probe.TOKENS["USDC"],
        token1=probe.TOKENS["WETH"],
        fee=500,
        block_timestamp=1_700_000_000,
    )
    assert row["sender"] == "0x1111111111111111111111111111111111111111"
    assert row["recipient"] == "0x2222222222222222222222222222222222222222"
    assert row["amount0_raw"] == "1500000000"
    assert row["amount1_raw"] == "-700000000000000000"
    assert row["tick"] == -12345


def test_gate_requires_density_and_clean_identity():
    result = {
        "endpoint_probe": {"selected": "https://example.invalid"},
        "decode_errors": [],
        "window_summaries": {f"w{i}": {"logs": 25} for i in range(4)},
    }
    rows = []
    for i in range(100):
        rows.append(
            {
                "block_hash": f"0x{i:064x}",
                "transaction_hash": f"0x{i + 1000:064x}",
                "log_index": 0,
                "block_timestamp": 1_700_000_000 + i,
            }
        )
    checks = probe.evaluate_gate(result, rows)
    assert all(checks.values())
    rows[-1] = dict(rows[0])
    assert probe.evaluate_gate(result, rows)["duplicate_identity_zero"] is False


def test_source_gate_purpose_forbids_outcomes():
    text = probe.PURPOSE.lower()
    for word in ("future return", "trade", "pnl", "model metric", "2024-2026", "order"):
        assert word in text
