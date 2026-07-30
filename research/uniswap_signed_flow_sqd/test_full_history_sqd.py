from __future__ import annotations

import json
from pathlib import Path

import full_history_sqd as f


def test_stable_flow_token_order_is_normalized() -> None:
    usdc = f.gate.TOKENS["USDC"]
    usdt = f.gate.TOKENS["USDT"]
    weth = f.gate.TOKENS["WETH"]
    decoded = {
        "amount0_raw": "2500000",
        "amount1_raw": "-1000000000000000000",
        "tick": 100,
    }
    flow, tick = f.stablecoin_flow_and_tick(
        decoded, {"token0": usdc, "token1": weth}
    )
    assert flow == 2.5 and tick == -100
    decoded = {
        "amount0_raw": "-1000000000000000000",
        "amount1_raw": "3000000",
        "tick": 200,
    }
    flow, tick = f.stablecoin_flow_and_tick(
        decoded, {"token0": weth, "token1": usdt}
    )
    assert flow == 3.0 and tick == 200


def test_bucket_features_are_exact() -> None:
    bucket = f.BucketAccumulator(1_700_000_000)
    bucket.add(
        pool_name="A",
        fee=500,
        signed_stable=3.0,
        normalized_weth_tick=10,
        transaction_hash="x",
        block_number=1,
    )
    bucket.add(
        pool_name="A",
        fee=500,
        signed_stable=-1.0,
        normalized_weth_tick=12,
        transaction_hash="y",
        block_number=2,
    )
    bucket.add(
        pool_name="B",
        fee=3000,
        signed_stable=2.0,
        normalized_weth_tick=20,
        transaction_hash="x",
        block_number=3,
    )
    out = bucket.finalize()
    assert out["gross_stable_notional"] == 6.0
    assert out["net_stable_notional"] == 4.0
    assert abs(out["signed_imbalance"] - 2 / 3) < 1e-12
    assert abs(out["aligned_gross_fraction"] - 5 / 6) < 1e-12
    assert out["swap_count"] == 3
    assert out["unique_transaction_count"] == 2
    assert abs(out["fee500_gross_fraction"] - 4 / 6) < 1e-12
    assert out["active_pool_count"] == 2


def test_source_gate_loader_requires_pass(tmp_path: Path) -> None:
    path = tmp_path / "gate.json"
    path.write_text(
        json.dumps(
            {
                "claim_id": f.CLAIM_ID,
                "source_gate_status": "SOURCE_UNAVAILABLE",
            }
        )
    )
    try:
        f.load_source_gate(path)
    except f.FullHistoryError:
        pass
    else:
        raise AssertionError("non-PASS source gate must not open history")


def test_filtered_portal_payload_advances_empty_chunk(monkeypatch) -> None:
    class Response:
        status_code = 204
        headers = {}
        text = ""

        def raise_for_status(self):
            return None

    client = f.FilteredPortalClient()
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(kwargs["json"])
        return Response()

    monkeypatch.setattr(client, "_request", fake_request)
    rows = list(
        client.stream_filtered(
            from_block=1,
            to_block=11,
            addresses=[next(iter(f.gate.EXPECTED_POOLS.values()))],
            topic0=f.gate.SWAP_TOPIC,
            max_block_span=5,
        )
    )
    assert rows == []
    assert [
        (item["fromBlock"], item["toBlock"]) for item in calls
    ] == [(1, 5), (6, 10), (11, 11)]


def test_full_source_contract_keeps_outcomes_closed() -> None:
    forbidden = {
        "future_return",
        "label",
        "action",
        "trade",
        "pnl",
        "model_metric",
    }
    assert not forbidden.intersection(set(vars(f)))
