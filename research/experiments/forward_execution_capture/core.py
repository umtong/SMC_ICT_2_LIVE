from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import hmac
import json
import os
from typing import Any, Iterable, Mapping

ZERO_HASH = "0" * 64


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


class NormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class CaptureRecord:
    capture_id: str
    connection_id: str
    venue: str
    channel: str
    local_wall_ns: int
    local_monotonic_ns: int
    exchange_event_ns: int
    sequence: int | None
    raw_sha256: str
    normalized: Mapping[str, Any]
    previous_hash: str
    record_hash: str


class HashChain:
    """Append-only deterministic record chain.

    It stores no credentials and performs no network or order-placement action.
    """

    def __init__(self, capture_id: str) -> None:
        if not capture_id:
            raise ValueError("capture_id is required")
        self.capture_id = capture_id
        self.records: list[CaptureRecord] = []
        self.terminal_hash = ZERO_HASH

    def append(
        self,
        *,
        connection_id: str,
        venue: str,
        channel: str,
        local_wall_ns: int,
        local_monotonic_ns: int,
        exchange_event_ns: int,
        sequence: int | None,
        raw_payload: bytes,
        normalized: Mapping[str, Any],
    ) -> CaptureRecord:
        raw_digest = sha256(raw_payload).hexdigest()
        body = {
            "capture_id": self.capture_id,
            "connection_id": connection_id,
            "venue": venue,
            "channel": channel,
            "local_wall_ns": int(local_wall_ns),
            "local_monotonic_ns": int(local_monotonic_ns),
            "exchange_event_ns": int(exchange_event_ns),
            "sequence": sequence,
            "raw_sha256": raw_digest,
            "normalized": normalized,
            "previous_hash": self.terminal_hash,
        }
        digest = sha256(bytes.fromhex(self.terminal_hash) + _canonical(body)).hexdigest()
        record = CaptureRecord(**body, record_hash=digest)
        self.records.append(record)
        self.terminal_hash = digest
        return record

    @staticmethod
    def verify(records: Iterable[CaptureRecord]) -> str:
        previous = ZERO_HASH
        for record in records:
            body = asdict(record)
            digest = body.pop("record_hash")
            if body["previous_hash"] != previous:
                raise ValueError("record-chain previous hash mismatch")
            expected = sha256(bytes.fromhex(previous) + _canonical(body)).hexdigest()
            if digest != expected:
                raise ValueError("record-chain digest mismatch")
            previous = digest
        return previous


def normalize_binance(
    message: Mapping[str, Any],
    *,
    local_wall_ns: int,
    local_monotonic_ns: int,
    connection_id: str,
) -> dict[str, Any]:
    event = str(message.get("e") or "")
    event_ms = int(message.get("E") or message.get("T") or 0)
    if event_ms <= 0:
        raise NormalizationError("Binance event timestamp missing")
    base = {
        "venue": "BINANCE_USDM",
        "connection_id": connection_id,
        "local_wall_ns": int(local_wall_ns),
        "local_monotonic_ns": int(local_monotonic_ns),
        "exchange_event_ns": event_ms * 1_000_000,
        "symbol": str(message.get("s") or message.get("o", {}).get("s") or ""),
    }
    if event == "bookTicker":
        return base | {
            "channel": "bookTicker",
            "sequence": int(message["u"]),
            "bid_price": str(message["b"]),
            "bid_qty": str(message["B"]),
            "ask_price": str(message["a"]),
            "ask_qty": str(message["A"]),
        }
    if event == "aggTrade":
        return base | {
            "channel": "aggTrade",
            "sequence": int(message["a"]),
            "price": str(message["p"]),
            "quantity": str(message["q"]),
            "buyer_is_maker": bool(message["m"]),
            "trade_time_ns": int(message["T"]) * 1_000_000,
        }
    if event == "forceOrder":
        order = message.get("o") or {}
        return base | {
            "channel": "forceOrder",
            "sequence": None,
            "side": str(order.get("S") or ""),
            "price": str(order.get("ap") or order.get("p") or "0"),
            "quantity": str(order.get("q") or "0"),
            "status": str(order.get("X") or ""),
            "trade_time_ns": int(order.get("T") or event_ms) * 1_000_000,
        }
    if event == "depthUpdate":
        return base | {
            "channel": "depth",
            "sequence": int(message["u"]),
            "first_update_id": int(message["U"]),
            "previous_update_id": int(message.get("pu", 0)),
            "bids": [[str(p), str(q)] for p, q in message.get("b", [])],
            "asks": [[str(p), str(q)] for p, q in message.get("a", [])],
        }
    raise NormalizationError(f"unsupported Binance event: {event}")


def normalize_bybit(
    message: Mapping[str, Any],
    *,
    local_wall_ns: int,
    local_monotonic_ns: int,
    connection_id: str,
) -> dict[str, Any]:
    topic = str(message.get("topic") or "")
    event_ms = int(message.get("ts") or 0)
    if event_ms <= 0:
        raise NormalizationError("Bybit event timestamp missing")
    data = message.get("data")
    base = {
        "venue": "BYBIT_LINEAR",
        "connection_id": connection_id,
        "local_wall_ns": int(local_wall_ns),
        "local_monotonic_ns": int(local_monotonic_ns),
        "exchange_event_ns": event_ms * 1_000_000,
        "topic": topic,
    }
    if topic.startswith("orderbook."):
        if not isinstance(data, Mapping):
            raise NormalizationError("Bybit orderbook data must be an object")
        return base | {
            "channel": "orderbook",
            "symbol": str(data.get("s") or ""),
            "sequence": int(data.get("seq") or data.get("u") or 0),
            "update_id": int(data.get("u") or 0),
            "message_type": str(message.get("type") or ""),
            "bids": [[str(p), str(q)] for p, q in data.get("b", [])],
            "asks": [[str(p), str(q)] for p, q in data.get("a", [])],
        }
    if topic.startswith("publicTrade."):
        rows = data if isinstance(data, list) else []
        return base | {
            "channel": "publicTrade",
            "symbol": topic.rsplit(".", 1)[-1],
            "sequence": None,
            "trades": [
                {
                    "trade_id": str(row.get("i") or ""),
                    "side": str(row.get("S") or ""),
                    "price": str(row.get("p") or "0"),
                    "quantity": str(row.get("v") or "0"),
                    "trade_time_ns": int(row.get("T") or event_ms) * 1_000_000,
                }
                for row in rows
            ],
        }
    if topic.startswith("allLiquidation."):
        rows = data if isinstance(data, list) else [data] if isinstance(data, Mapping) else []
        return base | {
            "channel": "allLiquidation",
            "symbol": topic.rsplit(".", 1)[-1],
            "sequence": None,
            "liquidations": [
                {
                    "side": str(row.get("S") or ""),
                    "price": str(row.get("p") or "0"),
                    "quantity": str(row.get("v") or "0"),
                    "updated_time_ns": int(row.get("T") or event_ms) * 1_000_000,
                }
                for row in rows
            ],
        }
    raise NormalizationError(f"unsupported Bybit topic: {topic}")


class RiskState(str, Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    DEFENSIVE = "DEFENSIVE"
    HALT = "HALT"

    @property
    def multiplier(self) -> float:
        return {
            RiskState.NORMAL: 1.0,
            RiskState.CAUTION: 0.5,
            RiskState.DEFENSIVE: 0.25,
            RiskState.HALT: 0.0,
        }[self]


class QualityMonitor:
    def __init__(self, *, max_future_skew_ns: int = 2_000_000_000, max_failures: int = 3) -> None:
        self.max_future_skew_ns = int(max_future_skew_ns)
        self.max_failures = int(max_failures)
        self.state = RiskState.NORMAL
        self.last_wall: dict[str, int] = {}
        self.last_mono: dict[str, int] = {}
        self.last_sequence: dict[tuple[str, str], int] = {}
        self.normalization_failures = 0
        self.reasons: list[str] = []

    def _halt(self, reason: str) -> RiskState:
        self.state = RiskState.HALT
        self.reasons.append(reason)
        return self.state

    def observe_clock(self, *, connection_id: str, wall_ns: int, monotonic_ns: int, exchange_ns: int) -> RiskState:
        if wall_ns < self.last_wall.get(connection_id, wall_ns):
            return self._halt("local wall clock regressed")
        if monotonic_ns <= self.last_mono.get(connection_id, monotonic_ns - 1):
            return self._halt("local monotonic clock did not increase")
        if exchange_ns > wall_ns + self.max_future_skew_ns:
            return self._halt("exchange timestamp is too far in the future")
        self.last_wall[connection_id] = wall_ns
        self.last_mono[connection_id] = monotonic_ns
        return self.state

    def observe_sequence(self, *, venue: str, channel: str, sequence: int, expected_previous: int | None = None) -> RiskState:
        key = (venue, channel)
        previous = self.last_sequence.get(key)
        if previous is not None and sequence <= previous:
            return self._halt("sequence regressed or repeated")
        if expected_previous is not None and previous is not None and expected_previous != previous:
            return self._halt("depth sequence gap")
        self.last_sequence[key] = sequence
        return self.state

    def observe_normalization_failure(self) -> RiskState:
        self.normalization_failures += 1
        if self.normalization_failures >= self.max_failures:
            return self._halt("normalization failure threshold reached")
        self.state = RiskState.CAUTION if self.normalization_failures == 1 else RiskState.DEFENSIVE
        return self.state


class BybitPrivateAuth:
    """Environment-only Bybit private websocket authentication helper."""

    @staticmethod
    def reject_secret_config(config: Mapping[str, Any]) -> None:
        forbidden = {"api_key", "api_secret", "secret", "token"}
        if any(str(key).lower() in forbidden for key in config):
            raise ValueError("credentials may not be stored in configuration")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BybitPrivateAuth":
        source = os.environ if env is None else env
        key = source.get("BYBIT_API_KEY")
        secret = source.get("BYBIT_API_SECRET")
        if not key or not secret:
            raise ValueError("BYBIT_API_KEY and BYBIT_API_SECRET are required")
        obj = cls()
        obj._api_key = key
        obj._api_secret = secret
        return obj

    def websocket_auth_args(self, expires_ms: int) -> list[str | int]:
        message = f"GET/realtime{int(expires_ms)}"
        signature = hmac.new(self._api_secret.encode(), message.encode(), "sha256").hexdigest()
        return [self._api_key, int(expires_ms), signature]


class PrivateLedger:
    """execId-authoritative execution/order/position reconciliation ledger."""

    def __init__(self) -> None:
        self.executions: dict[str, dict[str, Any]] = {}
        self.execution_qty_by_order: dict[str, Decimal] = {}
        self.orders: dict[str, dict[str, Any]] = {}
        self.position_ts: dict[tuple[str, int], int] = {}
        self.duplicate_terminal_updates = 0

    def on_execution(self, row: Mapping[str, Any]) -> bool:
        exec_id = str(row.get("execId") or "")
        order_id = str(row.get("orderId") or "")
        if not exec_id or not order_id:
            raise ValueError("execId and orderId are required")
        normalized = dict(row)
        if exec_id in self.executions:
            if self.executions[exec_id] != normalized:
                raise ValueError("conflicting duplicate execId")
            return False
        qty = _decimal(row.get("execQty") or 0)
        if qty < 0:
            raise ValueError("negative execution quantity")
        self.executions[exec_id] = normalized
        self.execution_qty_by_order[order_id] = self.execution_qty_by_order.get(order_id, Decimal(0)) + qty
        return True

    def on_order(self, row: Mapping[str, Any]) -> None:
        order_id = str(row.get("orderId") or "")
        if not order_id:
            raise ValueError("orderId is required")
        current = dict(row)
        prior = self.orders.get(order_id)
        cum = _decimal(current.get("cumExecQty") or 0)
        if prior is not None:
            previous_cum = _decimal(prior.get("cumExecQty") or 0)
            if cum < previous_cum:
                raise ValueError("order cumulative execution quantity regressed")
            if str(prior.get("orderStatus")) == "Filled" and str(current.get("orderStatus")) == "Filled":
                self.duplicate_terminal_updates += 1
        self.orders[order_id] = current

    def on_position(self, row: Mapping[str, Any]) -> None:
        key = (str(row.get("symbol") or ""), int(row.get("positionIdx") or 0))
        updated = int(row.get("updatedTime") or 0)
        if updated < self.position_ts.get(key, updated):
            raise ValueError("position timestamp regressed")
        self.position_ts[key] = updated

    def reconcile(self, tolerance: Decimal = Decimal("0")) -> list[str]:
        problems: list[str] = []
        for order_id, row in self.orders.items():
            order_cum = _decimal(row.get("cumExecQty") or 0)
            execution_cum = self.execution_qty_by_order.get(order_id, Decimal(0))
            if abs(order_cum - execution_cum) > tolerance:
                problems.append(f"{order_id}: order cumExecQty {order_cum} != executions {execution_cum}")
            if str(row.get("orderStatus")) == "Filled" and execution_cum == 0:
                problems.append(f"{order_id}: terminal Filled without execution")
        return problems


@dataclass(frozen=True)
class Signal:
    signal_id: str
    capture_id: str
    prefix_chain_sha256: str
    venue: str
    symbol: str
    side: str
    alpha_lcb_bps: float


class ExactPrefixShadow:
    """Freezes A/B execution routes at an exact capture-chain prefix."""

    def __init__(self, capture_id: str) -> None:
        self.capture_id = capture_id
        self.seen_prefixes: set[str] = {ZERO_HASH}
        self.decisions: dict[str, dict[str, Any]] = {}

    def observe_record(self, record: CaptureRecord) -> None:
        if record.capture_id != self.capture_id:
            raise ValueError("capture_id mismatch")
        self.seen_prefixes.add(record.record_hash)

    def submit(self, signal: Signal, *, maker_allowed: bool) -> dict[str, Any]:
        if signal.capture_id != self.capture_id:
            raise ValueError("signal capture_id mismatch")
        if signal.prefix_chain_sha256 not in self.seen_prefixes:
            raise ValueError("signal refers to an unseen capture prefix")
        if signal.signal_id in self.decisions:
            raise ValueError("signal_id already submitted")
        decision = {
            "signal_id": signal.signal_id,
            "prefix_chain_sha256": signal.prefix_chain_sha256,
            "dynamic_route": "MAKER" if maker_allowed else "TAKER",
            "benchmark_route": "TAKER",
            "venue": signal.venue,
            "symbol": signal.symbol,
            "side": signal.side,
            "alpha_lcb_bps": float(signal.alpha_lcb_bps),
        }
        self.decisions[signal.signal_id] = decision
        return decision
