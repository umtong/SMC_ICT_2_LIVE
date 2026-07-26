from __future__ import annotations

import argparse
import json
import math
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

import strict_guard as v3

base = v3.base
causal = v3.causal
CLAIM_ID = v3.CLAIM_ID
ENGINE = v3.ENGINE
CORRECTION_ID = (
    "CORRECTION-20260727-ML-STABLECOIN-SIMULTANEOUS-EVENT-"
    "LIQUIDATION-DISTANCE-004"
)
CORRECTION_FILE = Path(__file__).with_name(
    "CORRECTION_004_SIMULTANEOUS_EVENT_AND_LIQUIDATION_DISTANCE_BEFORE_OUTCOME.json"
)
ORIGINAL_STRICT_BUILD_ROWS = v3.strict_build_rows


def _load_correction() -> dict[str, Any]:
    correction = json.loads(CORRECTION_FILE.read_text(encoding="utf-8"))
    if correction.get("correction_id") != CORRECTION_ID:
        raise AssertionError("simultaneous-event/liquidation correction identity changed")
    if correction.get("recorded_before_source_result_or_market_outcome") is not True:
        raise AssertionError("correction was not frozen before outcome")
    return correction


def _strict_prior_event_state(
    events: pd.DataFrame,
    event_time_col: str,
) -> dict[str, tuple[float, float, int]]:
    """Return prior features using only availability seconds strictly before each group."""

    ordered = events.reset_index(drop=True).copy()
    ordered[event_time_col] = pd.to_numeric(ordered[event_time_col], errors="raise")
    ordered["amount_usd"] = pd.to_numeric(ordered["amount_usd"], errors="raise")
    ordered = ordered.sort_values([event_time_col, "event_id"]).reset_index(drop=True)

    window60: deque[tuple[int, int, float]] = deque()
    window24: deque[tuple[int, int, float]] = deque()
    same_direction_sum = {1: 0.0, -1: 0.0}
    net24 = 0.0
    result: dict[str, tuple[float, float, int]] = {}

    for timestamp_raw, group in ordered.groupby(event_time_col, sort=True):
        timestamp = int(timestamp_raw)
        while window60 and window60[0][0] < timestamp - 3_600:
            _, sign, amount = window60.popleft()
            same_direction_sum[sign] -= amount
        while window24 and window24[0][0] < timestamp - 86_400:
            _, sign, amount = window24.popleft()
            net24 -= sign * amount

        group_records: list[tuple[str, int, float]] = []
        for row in group.itertuples(index=False):
            event_id = str(getattr(row, "event_id"))
            direction = str(getattr(row, "direction")).upper()
            sign = 1 if direction == "MINT" else -1
            amount = float(getattr(row, "amount_usd"))
            result[event_id] = (
                max(0.0, same_direction_sum[sign]),
                float(net24),
                int(len(group)),
            )
            group_records.append((event_id, sign, amount))

        # Every event in this availability second receives the same strictly-prior
        # state. Add the full simultaneous group only after all assignments.
        for _, sign, amount in group_records:
            window60.append((timestamp, sign, amount))
            same_direction_sum[sign] += amount
            window24.append((timestamp, sign, amount))
            net24 += sign * amount

    return result


def strict_build_rows_v4(
    events: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    delay: int = 12,
) -> pd.DataFrame:
    if delay not in (12, 64):
        raise ValueError("delay must be 12 or 64")
    event_time_col = f"available_timestamp_{delay}"
    ordered = events.reset_index(drop=True).copy()
    ordered = ordered.sort_values([event_time_col, "event_id"]).reset_index(drop=True)
    prior = _strict_prior_event_state(ordered, event_time_col)
    rows = ORIGINAL_STRICT_BUILD_ROWS(ordered, bars, funding, delay)
    if rows.empty:
        return rows

    def prior_same(event_id: str) -> float:
        return math.log1p(prior[str(event_id)][0])

    def prior_net(event_id: str) -> float:
        value = prior[str(event_id)][1]
        return math.copysign(math.log1p(abs(value)), value) if value else 0.0

    rows["prior_60m_same_direction_event_notional"] = rows["event_id"].map(prior_same)
    rows["prior_24h_net_issuance"] = rows["event_id"].map(prior_net)
    rows["simultaneous_finalized_event_count"] = rows["event_id"].map(
        lambda event_id: prior[str(event_id)][2]
    )
    rows["prior_event_timestamp_rule"] = "STRICTLY_EARLIER_AVAILABILITY_SECOND"
    return rows.sort_values(["decision_ms", "event_id", "symbol"]).reset_index(drop=True)


def _actual_stop_distance(trade: base.Trade) -> float:
    if trade.exit_reason == "ENTRY_GAP_INVALIDATED_COST_ONLY":
        return 0.0
    if trade.entry <= 0:
        raise ValueError("trade entry must be positive")
    if trade.side == 1:
        return max(0.0, 1.0 - trade.stop_price / trade.entry)
    if trade.side == -1:
        return max(0.0, trade.stop_price / trade.entry - 1.0)
    raise ValueError(f"invalid trade side {trade.side}")


def strict_replay_v4(
    trades: list[base.Trade],
    cost_bps: float,
    period_start: str,
    period_end: str,
    risk: float = base.BASE_RISK,
    notional_cap: float = base.BASE_NOTIONAL_CAP,
) -> dict[str, Any]:
    """Size from pre-entry expected loss, but test liquidation from actual fill distance."""

    nav = base.INITIAL_NAV
    peak = nav
    mdd = 0.0
    liquidation = False
    ledger: list[dict[str, Any]] = []
    cost_fraction = cost_bps / 10_000.0

    for trade in trades:
        planned_stop_fraction = max(0.0, float(trade.stop_fraction))
        planned_stop_budget = planned_stop_fraction + cost_fraction
        leverage = min(notional_cap, risk / max(planned_stop_budget, 1e-9))
        actual_stop_fraction = _actual_stop_distance(trade)
        adverse_realized_gap_loss = (
            0.0
            if trade.exit_reason == "ENTRY_GAP_INVALIDATED_COST_ONLY"
            else max(0.0, -float(trade.gross_fraction))
        )
        liquidation_test_distance = max(
            actual_stop_fraction,
            adverse_realized_gap_loss,
        )
        liquidation_distance = (
            max(0.0, 1.0 / leverage - 0.005) if leverage > 1.0 else float("inf")
        )
        trade_liquidation = (
            leverage > 1.0
            and liquidation_test_distance >= liquidation_distance
        )
        if trade_liquidation:
            liquidation = True
            account_return = -1.0
        else:
            account_return = leverage * (
                float(trade.gross_fraction)
                + float(trade.funding_fraction)
                - cost_fraction
            )
        account_return = max(account_return, -1.0)

        before = nav
        nav *= 1.0 + account_return
        peak = max(peak, nav)
        mdd = max(mdd, 1.0 - nav / peak)
        ledger.append(
            {
                **asdict(trade),
                "leverage": leverage,
                "planned_stop_fraction": planned_stop_fraction,
                "planned_stop_budget_fraction": planned_stop_budget,
                "actual_structural_stop_fraction": actual_stop_fraction,
                "adverse_realized_gap_loss_fraction": adverse_realized_gap_loss,
                "liquidation_test_distance": liquidation_test_distance,
                "liquidation_distance": liquidation_distance,
                "liquidation_distance_rule": (
                    "ACTUAL_FILL_TO_STRUCTURAL_STOP_OR_ADVERSE_GAP"
                ),
                "trade_liquidation": trade_liquidation,
                "planned_account_loss_fraction_at_expected_stop": (
                    leverage * planned_stop_budget
                ),
                "actual_account_loss_fraction_at_structural_stop_before_gap": (
                    leverage * (actual_stop_fraction + cost_fraction)
                ),
                "account_return": account_return,
                "nav_before": before,
                "nav_after": nav,
                "pnl_usdt": nav - before,
            }
        )
        if nav <= 0:
            liquidation = True
            break

    start = base.utc_ts(period_start)
    end = base.utc_ts(period_end)
    days = max(1, int((end - start).total_seconds() // 86_400))
    total_return = nav / base.INITIAL_NAV - 1.0
    growth = (
        math.exp(math.log(max(nav / base.INITIAL_NAV, 1e-300)) / days) - 1.0
        if nav > 0
        else -1.0
    )
    pnl = np.array([row["pnl_usdt"] for row in ledger], dtype=float)
    positive = float(pnl[pnl > 0].sum())
    negative = float(-pnl[pnl < 0].sum())
    net_bps = np.array(
        [
            (
                row["gross_fraction"]
                + row["funding_fraction"]
                - cost_fraction
            )
            * 10_000.0
            for row in ledger
        ],
        dtype=float,
    )
    return {
        "trade_count": len(ledger),
        "ending_nav": nav,
        "total_return": total_return,
        "geometric_calendar_day_growth": growth,
        "profit_factor": (
            positive / negative
            if negative > 0
            else (float("inf") if positive > 0 else 0.0)
        ),
        "maximum_drawdown": mdd,
        "median_trade_bps": (
            float(np.median(net_bps)) if len(net_bps) else float("nan")
        ),
        "liquidation": liquidation,
        "boundary_mark_count": sum(
            row.get("exit_reason") == "MARK_TO_MARKET_STAGE_BOUNDARY"
            for row in ledger
        ),
        "forced_boundary_close": False,
        "liquidation_distance_rule": (
            "PLANNED_SIZE_ACTUAL_FILL_TO_STOP_LIQUIDATION_TEST"
        ),
        "ledger": ledger,
    }


def _patch_authorities() -> None:
    v3.strict_build_rows = strict_build_rows_v4
    causal.build_rows = strict_build_rows_v4
    base.replay = strict_replay_v4


def audit_v4(output: Path) -> dict[str, Any]:
    guard = v3.audit_result(output)
    result_path = output / "RESULT.json"
    full_path = output / "FULL_RESULT.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    full = json.loads(full_path.read_text(encoding="utf-8"))
    correction = {
        "correction_id": CORRECTION_ID,
        "simultaneous_event_prior_rule": (
            "STRICTLY_EARLIER_AVAILABILITY_SECOND_GROUPED_BEFORE_APPEND"
        ),
        "planned_quantity_rule": "PREENTRY_EXPECTED_STOP_DISTANCE_PLUS_COST",
        "liquidation_test_rule": (
            "ACTUAL_FILL_TO_STRUCTURAL_STOP_OR_ADVERSE_STOP_GAP"
        ),
        "entry_gap_cost_only_liquidation_distance": 0.0,
        "fatal_validity_violation": False,
    }
    for payload in (result, full):
        payload["simultaneous_event_and_liquidation_guard"] = correction
    v3._write_json(result_path, result)
    v3._write_json(full_path, full)
    if CORRECTION_FILE.is_file():
        (output / CORRECTION_FILE.name).write_bytes(CORRECTION_FILE.read_bytes())
    v3._refresh_hashes(output)
    return {"strict_causal_guard": guard, "v4_account_guard": correction}


def self_test() -> None:
    _load_correction()
    _patch_authorities()
    v3.self_test()

    times = pd.date_range("2021-01-01", periods=500, freq="1min", tz="UTC")
    prices = 100.0 + 0.001 * np.arange(len(times))
    frame = pd.DataFrame(
        {
            "open_time_ms": times.view("int64") // 1_000_000,
            "open": prices,
            "high": prices + 0.2,
            "low": prices - 0.2,
            "close": prices,
            "quote_volume": np.full(len(times), 1_000_000.0),
        }
    )
    prior_time = pd.Timestamp("2021-01-01 03:00:10", tz="UTC")
    group_time = pd.Timestamp("2021-01-01 03:10:30", tz="UTC")
    events = pd.DataFrame(
        [
            {
                "event_id": "prior",
                "token": "USDT",
                "direction": "MINT",
                "amount_usd": 10_000_000.0,
                "block_timestamp": int(prior_time.timestamp()) - 144,
                "available_timestamp_12": int(prior_time.timestamp()),
                "available_timestamp_64": int(prior_time.timestamp()) + 624,
            },
            {
                "event_id": "same-a",
                "token": "USDT",
                "direction": "MINT",
                "amount_usd": 20_000_000.0,
                "block_timestamp": int(group_time.timestamp()) - 144,
                "available_timestamp_12": int(group_time.timestamp()),
                "available_timestamp_64": int(group_time.timestamp()) + 624,
            },
            {
                "event_id": "same-b",
                "token": "USDC",
                "direction": "MINT",
                "amount_usd": 30_000_000.0,
                "block_timestamp": int(group_time.timestamp()) - 144,
                "available_timestamp_12": int(group_time.timestamp()),
                "available_timestamp_64": int(group_time.timestamp()) + 624,
            },
        ]
    )
    bars = {symbol: frame.copy() for symbol in base.SYMBOLS}
    funding = {
        symbol: pd.DataFrame({"time_ms": [], "rate": []})
        for symbol in base.SYMBOLS
    }
    rows = strict_build_rows_v4(events, bars, funding, 12)
    same = rows[rows["event_id"].isin(["same-a", "same-b"])]
    values = same.groupby("event_id")[
        "prior_60m_same_direction_event_notional"
    ].first()
    expected = math.log1p(10_000_000.0)
    if set(values.index) != {"same-a", "same-b"}:
        raise AssertionError(values)
    if not all(np.isclose(float(value), expected) for value in values):
        raise AssertionError(values)
    if set(same["simultaneous_finalized_event_count"].astype(int)) != {2}:
        raise AssertionError("simultaneous group count mismatch")

    trade = base.Trade(
        event_id="liq",
        symbol="BTCUSDT",
        decision_ms=0,
        entry_ms=60_000,
        exit_ms=120_000,
        side=1,
        entry=100.0,
        exit_price=101.0,
        stop_price=97.0,
        target_price=101.0,
        stop_fraction=0.005,
        gross_fraction=0.01,
        funding_fraction=0.0,
        model_probability_up=0.9,
        ev_bps=100.0,
        exit_reason="TARGET",
        ambiguous=False,
    )
    metrics = strict_replay_v4(
        [trade], 24.0, "2023-01-01", "2024-01-01", risk=0.60, notional_cap=100.0
    )
    if not metrics["liquidation"]:
        raise AssertionError("actual fill-to-stop liquidation was missed")
    ledger = metrics["ledger"][0]
    if not np.isclose(ledger["planned_stop_fraction"], 0.005):
        raise AssertionError(ledger)
    if not np.isclose(ledger["actual_structural_stop_fraction"], 0.03):
        raise AssertionError(ledger)

    cost_only = base.Trade(
        **{
            **asdict(trade),
            "event_id": "gap",
            "exit_price": trade.entry,
            "gross_fraction": 0.0,
            "exit_reason": "ENTRY_GAP_INVALIDATED_COST_ONLY",
        }
    )
    cost_metrics = strict_replay_v4(
        [cost_only],
        24.0,
        "2023-01-01",
        "2024-01-01",
        risk=0.60,
        notional_cap=100.0,
    )
    if cost_metrics["liquidation"]:
        raise AssertionError("cost-only entry invalidation created liquidation")
    if cost_metrics["ledger"][0]["liquidation_test_distance"] != 0.0:
        raise AssertionError(cost_metrics["ledger"][0])

    print("strict stablecoin simultaneous-event and liquidation-distance self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--events", type=Path, required=True)
    run_parser.add_argument("--market-cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _load_correction()
    _patch_authorities()
    if args.command == "self-test":
        self_test()
        return 0
    rc = v3.run(args)
    audit = audit_v4(args.output)
    print(json.dumps(audit, indent=2, sort_keys=True))
    if audit["strict_causal_guard"]["fatal_validity_violation"]:
        return 2
    result = json.loads((args.output / "RESULT.json").read_text(encoding="utf-8"))
    return (
        0
        if result.get("status")
        == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
