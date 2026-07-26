from __future__ import annotations

from dataclasses import dataclass

import pytest

import probe_aave_liquidations_bounded as bounded


@dataclass
class AlwaysUnavailable:
    calls: int = 0

    def call(self, method, params):
        self.calls += 1
        raise bounded.EndpointUnavailable("HTTP 429")


@dataclass
class RangeLimited:
    maximum_span: int
    calls: int = 0

    def call(self, method, params):
        self.calls += 1
        request = params[0]
        start = int(request["fromBlock"], 16)
        end = int(request["toBlock"], 16)
        if end - start + 1 > self.maximum_span:
            raise bounded.RangeTooLarge("explicit block range limit")
        return [{"start": start, "end": end}]


def test_rate_limit_does_not_recurse_by_block() -> None:
    rpc = AlwaysUnavailable()
    with pytest.raises(bounded.EndpointUnavailable):
        bounded.get_logs_bounded(
            rpc,
            address="0x" + "11" * 20,
            from_block=1,
            to_block=10_000,
            topic0="0x" + "22" * 32,
            maximum_chunk=2000,
        )
    assert rpc.calls == 1


def test_only_explicit_range_error_bisects_without_overlap() -> None:
    rpc = RangeLimited(maximum_span=4)
    rows = bounded.get_logs_bounded(
        rpc,
        address="0x" + "11" * 20,
        from_block=0,
        to_block=15,
        topic0="0x" + "22" * 32,
        maximum_chunk=16,
    )
    covered = []
    for row in rows:
        covered.extend(range(row["start"], row["end"] + 1))
    assert sorted(covered) == list(range(16))
    assert len(covered) == len(set(covered))
    assert rpc.calls < 16


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"code": -32005, "message": "block range is too wide"}, bounded.RangeTooLarge),
        ({"code": -32000, "message": "rate limit exceeded"}, bounded.EndpointUnavailable),
        ({"code": -32000, "message": "archive data unavailable"}, bounded.EndpointUnavailable),
        ({"code": -32602, "message": "invalid params"}, bounded.EndpointUnavailable),
    ],
)
def test_error_classification(payload, expected) -> None:
    assert bounded.classify_json_rpc_error(payload) is expected
