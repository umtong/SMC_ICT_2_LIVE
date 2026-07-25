from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

import cross_venue_pilot as v1

CAUSAL_VERSION = 2
LATENCY_DIAGNOSTICS: list[dict] = []


def _times(row: dict[str, str]) -> tuple[int, int]:
    exchange_ms = v1.timestamp_ms(row["timestamp"])
    local_ms = v1.timestamp_ms(row["local_timestamp"])
    return exchange_ms, local_ms


def _record_latency(path: Path, delays: list[int], exchange_monotonic: bool, local_monotonic: bool) -> None:
    values = np.asarray(delays, dtype=np.int64)
    LATENCY_DIAGNOSTICS.append({
        "path": str(path),
        "rows": int(len(values)),
        "local_timestamp_monotonic": bool(local_monotonic),
        "exchange_timestamp_monotonic": bool(exchange_monotonic),
        "negative_exchange_to_local_latency_count": int((values < 0).sum()),
        "exchange_to_local_latency_ms_median": float(np.median(values)) if len(values) else None,
        "exchange_to_local_latency_ms_p95": float(np.quantile(values, 0.95)) if len(values) else None,
        "exchange_to_local_latency_ms_max": int(values.max()) if len(values) else None,
    })


def read_trades_v2(path: Path) -> pd.DataFrame:
    buckets: dict[int, list[float]] = {}
    delays: list[int] = []
    previous_local: int | None = None
    previous_exchange: int | None = None
    local_monotonic = True
    exchange_monotonic = True
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "local_timestamp", "side", "price", "amount"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"trade schema missing {sorted(missing)}")
        for row in reader:
            exchange_ms, local_ms = _times(row)
            if previous_local is not None and local_ms < previous_local:
                local_monotonic = False
            if previous_exchange is not None and exchange_ms < previous_exchange:
                exchange_monotonic = False
            previous_local, previous_exchange = local_ms, exchange_ms
            delays.append(local_ms - exchange_ms)
            bucket = local_ms // v1.BUCKET_MS * v1.BUCKET_MS
            price, amount = float(row["price"]), float(row["amount"])
            if not (math.isfinite(price) and math.isfinite(amount) and price > 0 and amount > 0):
                continue
            notional = price * amount
            signed = notional if row["side"].strip().lower() == "buy" else -notional
            item = buckets.get(bucket)
            if item is None:
                buckets[bucket] = [notional, signed, price, 1.0]
            else:
                item[0] += notional
                item[1] += signed
                item[2] = price
                item[3] += 1.0
    if not local_monotonic:
        raise ValueError(f"local_timestamp is not monotonic in {path}")
    if not buckets:
        raise ValueError(f"no valid trades in {path}")
    _record_latency(path, delays, exchange_monotonic, local_monotonic)
    rows = [(key, *value) for key, value in buckets.items()]
    return pd.DataFrame(
        rows,
        columns=["bucket_ms", "trade_notional", "signed_notional", "last_trade", "trade_count"],
    ).sort_values("bucket_ms").set_index("bucket_ms")


def read_quotes_v2(path: Path) -> pd.DataFrame:
    buckets: dict[int, tuple[float, float, float, float, int]] = {}
    delays: list[int] = []
    previous_local: int | None = None
    previous_exchange: int | None = None
    local_monotonic = True
    exchange_monotonic = True
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "local_timestamp", "ask_price", "ask_amount", "bid_price", "bid_amount"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"quote schema missing {sorted(missing)}")
        for row in reader:
            exchange_ms, local_ms = _times(row)
            if previous_local is not None and local_ms < previous_local:
                local_monotonic = False
            if previous_exchange is not None and exchange_ms < previous_exchange:
                exchange_monotonic = False
            previous_local, previous_exchange = local_ms, exchange_ms
            delays.append(local_ms - exchange_ms)
            bucket = local_ms // v1.BUCKET_MS * v1.BUCKET_MS
            ask, ask_amount = float(row["ask_price"]), float(row["ask_amount"])
            bid, bid_amount = float(row["bid_price"]), float(row["bid_amount"])
            if not all(math.isfinite(value) for value in (ask, ask_amount, bid, bid_amount)):
                continue
            if ask <= bid or bid <= 0 or min(ask_amount, bid_amount) <= 0:
                continue
            # Last locally observed quote in a completed bucket is the state at bucket close.
            buckets[bucket] = (bid, bid_amount, ask, ask_amount, local_ms)
    if not local_monotonic:
        raise ValueError(f"local_timestamp is not monotonic in {path}")
    if not buckets:
        raise ValueError(f"no valid quotes in {path}")
    _record_latency(path, delays, exchange_monotonic, local_monotonic)
    rows = [(key, *value) for key, value in buckets.items()]
    return pd.DataFrame(
        rows,
        columns=["bucket_ms", "bid", "bid_amount", "ask", "ask_amount", "quote_event_ms"],
    ).sort_values("bucket_ms").set_index("bucket_ms")


def signal_events_v2(frame: pd.DataFrame, config: v1.Config, day: str, symbol: str) -> list[v1.Event]:
    raw = v1._signal_events_v1(frame, config, day, symbol)
    return [
        v1.Event(
            event.day,
            event.symbol,
            event.family,
            int(event.decision_ms + v1.BUCKET_MS),
            event.side,
            event.score,
            event.initial_basis_residual,
        )
        for event in raw
    ]


def simulate_v2(frame: pd.DataFrame, events: list[v1.Event], config: v1.Config, fee_bps_per_side: float) -> list[v1.Trade]:
    quote_rows = frame.loc[frame.bn_quote_actual].copy()
    if quote_rows.empty:
        return []
    quote_buckets = quote_rows.index.to_numpy(np.int64)
    quote_times = quote_rows.bn_quote_event_ms.to_numpy(np.int64)
    if np.any(np.diff(quote_times) < 0):
        raise ValueError("actual Binance quote local timestamps are not monotonic")
    frame_times = frame.index.to_numpy(np.int64)
    trades: list[v1.Trade] = []
    free_time = -1
    ordered = sorted(events, key=lambda item: (item.decision_ms, -item.score, item.symbol, item.family))
    for event in ordered:
        if event.decision_ms < free_time:
            continue
        target = event.decision_ms + config.latency_ms
        entry_pos = int(np.searchsorted(quote_times, target, side="left"))
        if entry_pos >= len(quote_times):
            continue
        entry_ms = int(quote_times[entry_pos])
        if entry_ms < target:
            raise AssertionError("entry preceded decision plus latency")
        entry_row = quote_rows.iloc[entry_pos]
        entry_fill = v1.execution_price(entry_row, event.side, True)
        if entry_fill is None:
            continue
        entry_price, entry_spread = entry_fill
        entry_mid = float(entry_row.bn_mid)
        stop = entry_mid - event.side * config.stop_spreads * entry_spread
        end_ms = entry_ms + config.hold_ms
        exit_pos = int(np.searchsorted(quote_times, end_ms, side="left"))
        exit_pos = min(exit_pos, len(quote_times) - 1)
        reason = "horizon"
        chosen = exit_pos
        initial_gap = abs(event.initial_basis_residual)
        for pos in range(entry_pos, exit_pos + 1):
            row = quote_rows.iloc[pos]
            mid = float(row.bn_mid)
            if (event.side > 0 and mid <= stop) or (event.side < 0 and mid >= stop):
                chosen, reason = pos, "protective_stop"
                break
            current_basis = math.log(float(row.bb_mid) / mid)
            bucket = int(quote_buckets[pos])
            history_end = int(np.searchsorted(frame_times, bucket, side="right"))
            start = max(0, history_end - 601)
            stop_at = max(start, history_end - 1)
            history = np.log(frame.bb_mid.iloc[start:stop_at]) - np.log(frame.bn_mid.iloc[start:stop_at])
            if len(history) >= 300:
                residual = current_basis - float(history.median())
                if initial_gap > 0 and abs(residual) <= 0.25 * initial_gap:
                    chosen, reason = pos, "cross_venue_convergence"
                    break
        exit_ms = int(quote_times[chosen])
        exit_row = quote_rows.iloc[chosen]
        exit_fill = v1.execution_price(exit_row, event.side, False)
        if exit_fill is None:
            continue
        exit_price, _ = exit_fill
        gross = event.side * math.log(exit_price / entry_price) * 10_000.0
        spread_bps = entry_spread / entry_mid * 10_000.0
        net = gross - 2.0 * fee_bps_per_side
        trades.append(
            v1.Trade(
                config.config_id,
                event.day,
                event.symbol,
                event.family,
                event.decision_ms,
                entry_ms,
                exit_ms,
                event.side,
                entry_price,
                exit_price,
                gross,
                spread_bps,
                fee_bps_per_side,
                net,
                reason,
                event.score,
            )
        )
        free_time = exit_ms + v1.BUCKET_MS
    return trades


def patch_v1() -> None:
    if not hasattr(v1, "_signal_events_v1"):
        v1._signal_events_v1 = v1.signal_events
    v1.read_trades = read_trades_v2
    v1.read_quotes = read_quotes_v2
    v1.signal_events = signal_events_v2
    v1.simulate = simulate_v2


def finalize_result(output: Path, result: dict) -> dict:
    result["causal_version"] = CAUSAL_VERSION
    result["availability_clock"] = "local_timestamp"
    result["bucket_availability"] = "bucket_end"
    result["event_order"] = "chronological_then_score_tie_break"
    result["v1_outputs_admissible"] = False
    result["source_latency_diagnostics"] = LATENCY_DIAGNOSTICS
    path = output / "PILOT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (output / "PILOT_RESULT.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8"
    )
    return result


def self_test() -> None:
    patch_v1()
    index = np.arange(0, 20_000, v1.BUCKET_MS, dtype=np.int64)
    frame = pd.DataFrame(index=index)
    for prefix in ("bn", "bb"):
        frame[f"{prefix}_bid"] = 99.9
        frame[f"{prefix}_ask"] = 100.1
        frame[f"{prefix}_bid_amount"] = 100.0
        frame[f"{prefix}_ask_amount"] = 100.0
        frame[f"{prefix}_quote_event_ms"] = index + 99
        frame[f"{prefix}_quote_actual"] = True
        frame[f"{prefix}_mid"] = 100.0
        frame[f"{prefix}_spread"] = 0.2
        frame[f"{prefix}_trade_notional"] = 0.0
        frame[f"{prefix}_signed_notional"] = 0.0
        frame[f"{prefix}_trade_count"] = 0.0
        frame[f"{prefix}_quote_imbalance"] = 0.0
    frame.loc[5000:5900, "bb_mid"] = np.linspace(100, 101, 10)
    frame.loc[5000:5900, "bb_bid"] = frame.loc[5000:5900, "bb_mid"] - 0.1
    frame.loc[5000:5900, "bb_ask"] = frame.loc[5000:5900, "bb_mid"] + 0.1
    frame.loc[5000:5900, "bb_trade_notional"] = 1000.0
    frame.loc[5000:5900, "bb_signed_notional"] = 900.0
    config = v1.Config("bybit_to_binance_propagation", 1000, 4.0, 0.60, 0.50, 500, 3000, 4.0, 2.0)
    events = signal_events_v2(frame, config, "synthetic", "BTCUSDT")
    assert events
    assert all(event.decision_ms % v1.BUCKET_MS == 0 for event in events)
    assert min(event.decision_ms for event in events) > 5000
    trades = simulate_v2(frame, events, config, 0.0)
    assert all(item.entry_ms >= item.decision_ms + 500 for item in trades)
    changed = frame.copy()
    changed.loc[15000:, "bb_mid"] *= 2.0
    prefix_a = signal_events_v2(frame, config, "synthetic", "BTCUSDT")
    prefix_b = signal_events_v2(changed, config, "synthetic", "BTCUSDT")
    assert [(x.decision_ms, x.side) for x in prefix_a if x.decision_ms < 15000] == [
        (x.decision_ms, x.side) for x in prefix_b if x.decision_ms < 15000
    ]
    deliberately_reversed = [
        v1.Event("d", "BTCUSDT", "f", 2000, 1, 100.0, 1.0),
        v1.Event("d", "BTCUSDT", "f", 1000, 1, 1.0, 1.0),
    ]
    assert [event.decision_ms for event in sorted(deliberately_reversed, key=lambda item: (item.decision_ms, -item.score))] == [1000, 2000]
    print("cross-venue causal V2 self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    patch_v1()
    if args.self_test:
        self_test()
        return 0
    LATENCY_DIAGNOSTICS.clear()
    result = v1.run(args.output, args.cache)
    result = finalize_result(args.output, result)
    print(json.dumps({"causal_version": 2, "fatal_edge_pass_count": result["fatal_edge_pass_count"], "best": result["best"]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
