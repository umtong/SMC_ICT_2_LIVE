from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import hmac
import json

import pytest

from research.experiments.forward_execution_capture import (
    BybitPrivateAuth,
    CaptureRecord,
    ExactPrefixShadow,
    HashChain,
    NormalizationError,
    PrivateLedger,
    QualityMonitor,
    RiskState,
    Signal,
    normalize_binance,
    normalize_bybit,
)


def test_binance_book_ticker_normalization():
    row = normalize_binance(
        {"e": "bookTicker", "E": 1000, "u": 9, "s": "BTCUSDT", "b": "100", "B": "2", "a": "101", "A": "3"},
        local_wall_ns=1_100_000_000,
        local_monotonic_ns=10,
        connection_id="c1",
    )
    assert row["exchange_event_ns"] == 1_000_000_000
    assert row["sequence"] == 9
    assert row["ask_price"] == "101"


def test_binance_agg_trade_normalization():
    row = normalize_binance(
        {"e": "aggTrade", "E": 1000, "T": 999, "a": 77, "s": "ETHUSDT", "p": "2", "q": "4", "m": True},
        local_wall_ns=1_100_000_000,
        local_monotonic_ns=10,
        connection_id="c1",
    )
    assert row["trade_time_ns"] == 999_000_000
    assert row["buyer_is_maker"] is True


def test_binance_rejects_unknown_event():
    with pytest.raises(NormalizationError):
        normalize_binance({"e": "unknown", "E": 1}, local_wall_ns=2, local_monotonic_ns=1, connection_id="c")


def test_bybit_orderbook_normalization():
    row = normalize_bybit(
        {"topic": "orderbook.50.BTCUSDT", "type": "delta", "ts": 1000, "data": {"s": "BTCUSDT", "u": 11, "seq": 22, "b": [["1", "2"]], "a": [["3", "4"]]}},
        local_wall_ns=1_100_000_000,
        local_monotonic_ns=10,
        connection_id="b1",
    )
    assert row["channel"] == "orderbook"
    assert row["sequence"] == 22
    assert row["bids"] == [["1", "2"]]


def test_bybit_liquidation_normalization():
    row = normalize_bybit(
        {"topic": "allLiquidation.BTCUSDT", "ts": 1000, "data": [{"S": "Sell", "p": "10", "v": "2", "T": 999}]},
        local_wall_ns=1_100_000_000,
        local_monotonic_ns=10,
        connection_id="b1",
    )
    assert row["liquidations"][0]["updated_time_ns"] == 999_000_000


def test_hash_chain_round_trip():
    chain = HashChain("cap")
    first = chain.append(connection_id="c", venue="V", channel="x", local_wall_ns=2, local_monotonic_ns=1, exchange_event_ns=1, sequence=1, raw_payload=b"{}", normalized={"x": 1})
    second = chain.append(connection_id="c", venue="V", channel="x", local_wall_ns=3, local_monotonic_ns=2, exchange_event_ns=2, sequence=2, raw_payload=b"[]", normalized={"x": 2})
    assert second.previous_hash == first.record_hash
    assert HashChain.verify(chain.records) == chain.terminal_hash


def test_hash_chain_detects_tamper():
    chain = HashChain("cap")
    row = chain.append(connection_id="c", venue="V", channel="x", local_wall_ns=2, local_monotonic_ns=1, exchange_event_ns=1, sequence=1, raw_payload=b"{}", normalized={"x": 1})
    with pytest.raises(ValueError):
        HashChain.verify([replace(row, normalized={"x": 9})])


def test_quality_monitor_clock_regression_halts():
    q = QualityMonitor()
    assert q.observe_clock(connection_id="c", wall_ns=100, monotonic_ns=10, exchange_ns=90) == RiskState.NORMAL
    assert q.observe_clock(connection_id="c", wall_ns=99, monotonic_ns=11, exchange_ns=90) == RiskState.HALT
    assert q.state.multiplier == 0


def test_quality_monitor_sequence_gap_halts():
    q = QualityMonitor()
    q.observe_sequence(venue="V", channel="depth", sequence=10)
    assert q.observe_sequence(venue="V", channel="depth", sequence=12, expected_previous=9) == RiskState.HALT


def test_quality_monitor_failure_ladder():
    q = QualityMonitor(max_failures=3)
    assert q.observe_normalization_failure() == RiskState.CAUTION
    assert q.observe_normalization_failure() == RiskState.DEFENSIVE
    assert q.observe_normalization_failure() == RiskState.HALT


def test_bybit_auth_is_environment_only():
    auth = BybitPrivateAuth.from_env({"BYBIT_API_KEY": "k", "BYBIT_API_SECRET": "s"})
    args = auth.websocket_auth_args(123)
    expected = hmac.new(b"s", b"GET/realtime123", "sha256").hexdigest()
    assert args == ["k", 123, expected]


def test_bybit_auth_rejects_secret_config():
    with pytest.raises(ValueError):
        BybitPrivateAuth.reject_secret_config({"api_secret": "do-not-store"})


def test_private_ledger_duplicate_exec_is_idempotent():
    ledger = PrivateLedger()
    row = {"execId": "e1", "orderId": "o1", "execQty": "2"}
    assert ledger.on_execution(row) is True
    assert ledger.on_execution(row) is False
    assert ledger.execution_qty_by_order["o1"] == Decimal("2")


def test_private_ledger_conflicting_exec_rejected():
    ledger = PrivateLedger()
    ledger.on_execution({"execId": "e1", "orderId": "o1", "execQty": "2"})
    with pytest.raises(ValueError):
        ledger.on_execution({"execId": "e1", "orderId": "o1", "execQty": "3"})


def test_private_ledger_reconciles_order_and_execution():
    ledger = PrivateLedger()
    ledger.on_execution({"execId": "e1", "orderId": "o1", "execQty": "2"})
    ledger.on_order({"orderId": "o1", "cumExecQty": "2", "orderStatus": "Filled"})
    assert ledger.reconcile() == []


def test_private_ledger_detects_missing_execution():
    ledger = PrivateLedger()
    ledger.on_order({"orderId": "o1", "cumExecQty": "1", "orderStatus": "Filled"})
    assert len(ledger.reconcile()) == 2


def test_private_ledger_order_regression_rejected():
    ledger = PrivateLedger()
    ledger.on_order({"orderId": "o1", "cumExecQty": "2", "orderStatus": "PartiallyFilled"})
    with pytest.raises(ValueError):
        ledger.on_order({"orderId": "o1", "cumExecQty": "1", "orderStatus": "PartiallyFilled"})


def test_private_ledger_position_time_regression_rejected():
    ledger = PrivateLedger()
    ledger.on_position({"symbol": "BTCUSDT", "positionIdx": 0, "updatedTime": 20})
    with pytest.raises(ValueError):
        ledger.on_position({"symbol": "BTCUSDT", "positionIdx": 0, "updatedTime": 19})


def test_exact_prefix_shadow_routes_and_freezes_benchmark():
    chain = HashChain("cap")
    record = chain.append(connection_id="c", venue="V", channel="x", local_wall_ns=2, local_monotonic_ns=1, exchange_event_ns=1, sequence=1, raw_payload=b"{}", normalized={"x": 1})
    shadow = ExactPrefixShadow("cap")
    shadow.observe_record(record)
    decision = shadow.submit(Signal("s1", "cap", record.record_hash, "V", "BTCUSDT", "Buy", 9.0), maker_allowed=True)
    assert decision["dynamic_route"] == "MAKER"
    assert decision["benchmark_route"] == "TAKER"


def test_exact_prefix_shadow_rejects_unseen_prefix():
    shadow = ExactPrefixShadow("cap")
    with pytest.raises(ValueError):
        shadow.submit(Signal("s1", "cap", "f" * 64, "V", "BTCUSDT", "Buy", 9.0), maker_allowed=False)


def test_module_has_no_order_placement_api():
    import research.experiments.forward_execution_capture.core as core
    names = {name.lower() for name in dir(core)}
    assert "place_order" not in names
    assert "submit_order" not in names


def test_source_manifest_matches_readable_files():
    root = Path(__file__).parents[1]
    manifest = json.loads(
        (root / "research/experiments/forward_execution_capture/SOURCE_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["format"] == "readable_source_files"
    assert manifest["file_count"] == len(manifest["files"])
    for row in manifest["files"]:
        path = root / row["path"]
        assert path.is_file()
        assert path.stat().st_size == row["size_bytes"]
        assert sha256(path.read_bytes()).hexdigest() == row["sha256"]
