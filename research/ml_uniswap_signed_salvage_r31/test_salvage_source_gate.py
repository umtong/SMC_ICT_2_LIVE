from __future__ import annotations

from typing import Any

import salvage_source_gate as s


def test_first_at_or_after_caches_final_lower_bound() -> None:
    class Fake(s.PacedTransport):
        def __init__(self) -> None:
            pass

        def rpc(self, method: str, params: list[Any], attempts: int = 8) -> str:
            assert method == "eth_blockNumber"
            return hex(20)

        def block_timestamp(self, block: int, cache: dict[int, int]) -> int:
            cache[int(block)] = int(block) * 10
            return cache[int(block)]

    cache: dict[int, int] = {}
    value = Fake().first_at_or_after(55, cache)
    assert value == 6
    assert cache[value] == 60


def test_logs_adaptive_bisects_only_range_errors() -> None:
    class Fake(s.PacedTransport):
        def __init__(self) -> None:
            pass

        def rpc(
            self, method: str, params: list[Any], attempts: int = 8
        ) -> list[dict[str, str]]:
            assert method == "eth_getLogs"
            request = params[0]
            start = int(request["fromBlock"], 16)
            end = int(request["toBlock"], 16)
            if start < end:
                raise RuntimeError("query returned more than provider limit")
            return [{"blockNumber": hex(start)}]

    rows = Fake().logs_adaptive(
        address="0x" + "11" * 20,
        from_block=10,
        to_block=13,
        topic0="0xabc",
    )
    assert [int(row["blockNumber"], 16) for row in rows] == [10, 11, 12, 13]


def test_logs_adaptive_fails_closed_on_transport_error() -> None:
    class Fake(s.PacedTransport):
        def __init__(self) -> None:
            pass

        def rpc(
            self, method: str, params: list[Any], attempts: int = 8
        ) -> list[dict[str, str]]:
            raise RuntimeError("HTTP 429")

    try:
        Fake().logs_adaptive(
            address="0x" + "22" * 20,
            from_block=1,
            to_block=3,
            topic0="0xdef",
        )
    except RuntimeError as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("transport failure must not be treated as a range split")
