from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_ROOT = REPO_ROOT / "research" / "ml_stablecoin_issuance_economic_20260726"
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

import run_causal as causal  # noqa: E402

base = causal.base
CLAIM_ID = base.CLAIM_ID
ENGINE = "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_STRICT_CAUSAL_V3"
CORRECTION_ID = "CORRECTION-20260727-ML-STABLECOIN-PREENTRY-INFORMATION-BOUNDARY-002"
LEGACY_CORRECTION_ID = "CORRECTION-20260726-ML-STABLECOIN-ENTRY-BAR-CAUSALITY-001"


def _latest_completed_index(times: np.ndarray, decision_ms: int) -> int:
    close_boundaries = times + 60_000
    return int(np.searchsorted(close_boundaries, decision_ms, side="right")) - 1


def strict_build_rows(
    events: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    delay: int = 12,
) -> pd.DataFrame:
    """Build source-event rows with a hard pre-entry information boundary.

    The event can become finalized at any second. The next-minute open is an
    execution price, not a feature or a decision-time filter. Every market
    feature and frozen liquidity level ends at the latest bar whose close is
    already available at the finalized source timestamp.
    """

    del funding
    if delay not in (12, 64):
        raise ValueError("delay must be 12 or 64")
    events = events.reset_index(drop=True).copy()
    event_time_col = f"available_timestamp_{delay}"
    signed = np.where(
        events["direction"].astype(str).str.upper().eq("MINT"), 1.0, -1.0
    )
    event_seconds = events[event_time_col].to_numpy(np.int64)
    amounts = events["amount_usd"].to_numpy(float)
    prior_same = np.zeros(len(events), dtype=float)
    prior_net = np.zeros(len(events), dtype=float)
    left60 = 0
    left24 = 0
    for i in range(len(events)):
        while left60 < i and event_seconds[left60] < event_seconds[i] - 3_600:
            left60 += 1
        while left24 < i and event_seconds[left24] < event_seconds[i] - 86_400:
            left24 += 1
        same_mask = signed[left60:i] == signed[i]
        prior_same[i] = (
            float(amounts[left60:i][same_mask].sum()) if i > left60 else 0.0
        )
        prior_net[i] = (
            float(np.sum(amounts[left24:i] * signed[left24:i]))
            if i > left24
            else 0.0
        )

    feature_arrays = {
        symbol: base._returns_features(frame) for symbol, frame in bars.items()
    }
    rows: list[dict[str, Any]] = []
    per_event_ret15: dict[str, dict[str, float]] = {}

    for i, event in events.iterrows():
        decision_ms = int(event[event_time_col]) * 1_000
        event_id = str(event["event_id"])
        per_event_ret15[event_id] = {}
        for symbol in base.SYMBOLS:
            frame = bars[symbol]
            times = frame["open_time_ms"].to_numpy(np.int64)
            next_open_ms = ((decision_ms // 60_000) + 1) * 60_000
            entry_index = base._index_at_or_after(times, next_open_ms)
            if entry_index is None:
                continue
            completed_index = _latest_completed_index(times, decision_ms)
            if completed_index < 60 or completed_index >= entry_index:
                continue

            completed_window = frame.iloc[completed_index - 59 : completed_index + 1]
            if len(completed_window) != 60:
                continue
            upper = float(completed_window["high"].max())
            lower = float(completed_window["low"].min())
            decision_reference = float(frame.iloc[completed_index]["close"])
            if not (
                np.isfinite(upper)
                and np.isfinite(lower)
                and np.isfinite(decision_reference)
                and upper > decision_reference > lower > 0
            ):
                continue

            entry = float(frame.iloc[entry_index]["open"])
            arrays = feature_arrays[symbol]
            ret15 = float(arrays["ret15"][completed_index])
            vol60 = float(arrays["vol60"][completed_index])
            eff60 = float(arrays["eff60"][completed_index])
            per_event_ret15[event_id][symbol] = ret15
            upper_distance = upper / decision_reference - 1.0
            lower_distance = 1.0 - lower / decision_reference

            boundary = base.label_boundary_ms(decision_ms)
            boundary_index = int(np.searchsorted(times, boundary, side="left")) - 1
            if boundary_index < entry_index:
                continue
            exit_index = boundary_index
            label = np.nan
            ambiguous = False
            reason = "UNRESOLVED_AT_STAGE_BOUNDARY"
            for k in range(entry_index, boundary_index + 1):
                high = float(frame.iloc[k]["high"])
                low = float(frame.iloc[k]["low"])
                hit_up = high >= upper
                hit_down = low <= lower
                if hit_up and hit_down:
                    exit_index = k
                    ambiguous = True
                    reason = "AMBIGUOUS"
                    break
                if hit_up:
                    exit_index = k
                    label = 1.0
                    reason = "UPPER_FIRST"
                    break
                if hit_down:
                    exit_index = k
                    label = 0.0
                    reason = "LOWER_FIRST"
                    break

            rows.append(
                {
                    "event_id": event_id,
                    "symbol": symbol,
                    "decision_ms": decision_ms,
                    "feature_available_through_ms": int(times[completed_index] + 60_000),
                    "completed_feature_index": completed_index,
                    "decision_reference_price": decision_reference,
                    "entry_index": entry_index,
                    "entry_ms": int(times[entry_index]),
                    "exit_index": exit_index,
                    "exit_ms": int(times[exit_index]),
                    "stage_boundary_ms": int(boundary),
                    "entry": entry,
                    "entry_gap_invalidated": not (upper > entry > lower),
                    "upper": upper,
                    "lower": lower,
                    "label_up": label,
                    "ambiguous": ambiguous,
                    "path_reason": reason,
                    "log_event_usd_notional": math.log1p(
                        max(float(event["amount_usd"]), 0.0)
                    ),
                    "mint_or_burn": (
                        1.0 if str(event["direction"]).upper() == "MINT" else -1.0
                    ),
                    "usdt_or_usdc": (
                        1.0 if str(event["token"]).upper() == "USDT" else 0.0
                    ),
                    "prior_60m_same_direction_event_notional": math.log1p(
                        max(prior_same[i], 0.0)
                    ),
                    "prior_24h_net_issuance": (
                        math.copysign(math.log1p(abs(prior_net[i])), prior_net[i])
                        if prior_net[i]
                        else 0.0
                    ),
                    "event_block_gas_utilization": float(
                        event.get("gas_utilization", np.nan)
                    ),
                    "prior_15m_return": ret15,
                    "prior_60m_realized_volatility": vol60,
                    "prior_60m_path_efficiency": eff60,
                    "distance_to_frozen_upper_60m_liquidity": upper_distance,
                    "distance_to_frozen_lower_60m_liquidity": lower_distance,
                }
            )

    output = pd.DataFrame(rows)
    if output.empty:
        return output
    breadth: dict[str, float] = {}
    for event_id, item in per_event_ret15.items():
        values = [item.get(symbol, np.nan) for symbol in base.SYMBOLS]
        finite = [value for value in values if np.isfinite(value)]
        breadth[event_id] = (
            float(np.mean(np.sign(finite))) if finite else float("nan")
        )
    output["btc_eth_completed_return_breadth"] = output["event_id"].map(breadth)
    return output.sort_values(["decision_ms", "event_id", "symbol"]).reset_index(
        drop=True
    )


def strict_trade_from_row(
    row: pd.Series,
    p_up: float,
    cost_bps: float,
    bars: pd.DataFrame,
    funding: pd.DataFrame,
) -> base.Trade | None:
    """Freeze side before entry; future entry price affects execution only."""

    upper_distance = float(row["distance_to_frozen_upper_60m_liquidity"])
    lower_distance = float(row["distance_to_frozen_lower_60m_liquidity"])
    cost_fraction = cost_bps / 10_000.0
    ev_long = (
        p_up * upper_distance
        - (1.0 - p_up) * lower_distance
        - cost_fraction
    )
    ev_short = (
        (1.0 - p_up) * lower_distance
        - p_up * upper_distance
        - cost_fraction
    )
    if max(ev_long, ev_short) <= 0:
        return None
    side = 1 if ev_long >= ev_short else -1

    if bool(row.get("entry_gap_invalidated", False)):
        entry = float(row["entry"])
        upper = float(row["upper"])
        lower = float(row["lower"])
        return base.Trade(
            event_id=str(row["event_id"]),
            symbol=str(row["symbol"]),
            decision_ms=int(row["decision_ms"]),
            entry_ms=int(row["entry_ms"]),
            exit_ms=int(row["entry_ms"]),
            side=side,
            entry=entry,
            exit_price=entry,
            stop_price=lower if side == 1 else upper,
            target_price=upper if side == 1 else lower,
            stop_fraction=(lower_distance if side == 1 else upper_distance),
            gross_fraction=0.0,
            funding_fraction=0.0,
            model_probability_up=float(p_up),
            ev_bps=float(max(ev_long, ev_short) * 10_000.0),
            exit_reason="ENTRY_GAP_INVALIDATED_COST_ONLY",
            ambiguous=False,
        )

    return causal.trade_from_row(row, p_up, cost_bps, bars, funding)


causal.build_rows = strict_build_rows
base.trade_from_row = strict_trade_from_row


def run(args: argparse.Namespace) -> int:
    return causal.run(args)


def _walk(value: Any, state: dict[str, Any], prefix: str = "$") -> None:
    if isinstance(value, dict):
        reason = value.get("exit_reason")
        if reason == "SOURCE_BOUNDARY":
            state["legacy_source_boundary_paths"].append(
                f"{prefix}:{value.get('event_id','UNKNOWN')}:{value.get('symbol','UNKNOWN')}"
            )
        elif reason == "MARK_TO_MARKET_STAGE_BOUNDARY":
            state["boundary_mark_count"] += 1
        elif reason == "ENTRY_GAP_INVALIDATED_COST_ONLY":
            state["entry_gap_cost_only_count"] += 1
        if value.get("forced_boundary_close") is True:
            state["forced_boundary_close_true_paths"].append(prefix)
        for key, child in value.items():
            _walk(child, state, f"{prefix}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk(child, state, f"{prefix}[{index}]")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(base.json_safe(payload), indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _refresh_hashes(output: Path) -> None:
    files = [
        path
        for path in output.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output / "SHA256SUMS.txt").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in sorted(files)
        ),
        encoding="utf-8",
    )


def audit_result(output: Path) -> dict[str, Any]:
    result_path = output / "RESULT.json"
    full_path = output / "FULL_RESULT.json"
    if not result_path.is_file() or not full_path.is_file():
        raise FileNotFoundError("economic result files missing")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    full = json.loads(full_path.read_text(encoding="utf-8"))
    state: dict[str, Any] = {
        "legacy_source_boundary_paths": [],
        "forced_boundary_close_true_paths": [],
        "boundary_mark_count": 0,
        "entry_gap_cost_only_count": 0,
    }
    _walk(full, state)
    state["legacy_source_boundary_paths"] = sorted(
        set(state["legacy_source_boundary_paths"])
    )
    state["forced_boundary_close_true_paths"] = sorted(
        set(state["forced_boundary_close_true_paths"])
    )
    fatal = bool(
        state["legacy_source_boundary_paths"]
        or state["forced_boundary_close_true_paths"]
    )
    guard = {
        "correction_id": CORRECTION_ID,
        "legacy_correction_id": LEGACY_CORRECTION_ID,
        "engine": ENGINE,
        "source_decision_second_respected": True,
        "latest_completed_bar_cutoff_enforced": True,
        "decision_reference_price_pre_entry": True,
        "future_entry_open_used_for_model_or_action": False,
        "entry_open_used_for_realized_execution_only": True,
        "entry_gap_rule": "ZERO_GROSS_COST_ONLY_NO_ALTERNATIVE_REROUTE",
        "stage_boundary_positions_marked_not_closed": True,
        "boundary_mark_count": int(state["boundary_mark_count"]),
        "entry_gap_cost_only_count": int(state["entry_gap_cost_only_count"]),
        "legacy_source_boundary_paths": state["legacy_source_boundary_paths"],
        "forced_boundary_close_true_paths": state[
            "forced_boundary_close_true_paths"
        ],
        "fatal_validity_violation": fatal,
    }
    for payload in (result, full):
        payload["engine"] = ENGINE
        payload["strict_causal_guard"] = guard
        payload["official_2024h1_opened"] = False
        payload["official_2024_2026_opened"] = False
    if fatal:
        for payload in (result, full):
            payload["status"] = "PRE2024_INVALID_STRICT_CAUSAL_GUARD"
            payload.setdefault("development_gate", {})["strict_causal_guard"] = False
            payload["development_gate"]["all"] = False
    else:
        for payload in (result, full):
            payload.setdefault("development_gate", {})["strict_causal_guard"] = True
            if payload.get("development_opened"):
                payload["development_gate"]["all"] = all(
                    bool(value)
                    for key, value in payload["development_gate"].items()
                    if key != "all"
                )
                if payload["development_gate"]["all"]:
                    payload["status"] = "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
                elif payload.get("status") == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1":
                    payload["status"] = "PRE2024_BELOW_GATE"

    correction_path = Path(__file__).with_name(
        "CORRECTION_002_PREENTRY_INFORMATION_BOUNDARY_BEFORE_OUTCOME.json"
    )
    if correction_path.is_file():
        (output / correction_path.name).write_bytes(correction_path.read_bytes())
    _write_json(result_path, result)
    _write_json(full_path, full)
    _refresh_hashes(output)
    return guard


def self_test() -> None:
    causal.self_test()
    times = pd.date_range("2021-01-01", periods=400, freq="1min", tz="UTC")
    base_price = 100.0 + 0.01 * np.arange(len(times))
    frame = pd.DataFrame(
        {
            "open_time_ms": times.view("int64") // 1_000_000,
            "open": base_price,
            "high": base_price + 0.25,
            "low": base_price - 0.25,
            "close": base_price,
            "quote_volume": np.full(len(times), 1_000_000.0),
        }
    )
    event_time = pd.Timestamp("2021-01-01 03:10:30", tz="UTC")
    events = pd.DataFrame(
        [
            {
                "event_id": "event",
                "token": "USDT",
                "direction": "MINT",
                "amount_usd": 50_000_000.0,
                "block_timestamp": int(event_time.timestamp()) - 144,
                "available_timestamp_12": int(event_time.timestamp()),
                "available_timestamp_64": int(event_time.timestamp()) + 624,
            }
        ]
    )
    bars = {symbol: frame.copy() for symbol in base.SYMBOLS}
    funding = {
        symbol: pd.DataFrame({"time_ms": [], "rate": []})
        for symbol in base.SYMBOLS
    }
    rows = strict_build_rows(events, bars, funding, 12)
    if rows.empty:
        raise AssertionError("strict synthetic row missing")
    row = rows.iloc[0]
    expected_completed = int(
        np.searchsorted(
            frame["open_time_ms"].to_numpy(np.int64) + 60_000,
            int(event_time.timestamp() * 1_000),
            side="right",
        )
        - 1
    )
    if int(row["completed_feature_index"]) != expected_completed:
        raise AssertionError((row["completed_feature_index"], expected_completed))
    if int(row["feature_available_through_ms"]) > int(event_time.timestamp() * 1_000):
        raise AssertionError("feature cutoff exceeds source decision")

    mutated = frame.copy()
    entry_index = int(row["entry_index"])
    incomplete_index = expected_completed + 1
    mutated.loc[incomplete_index, ["high", "low", "close"]] = [999.0, 1.0, 500.0]
    mutated.loc[entry_index, "open"] = float(row["upper"]) * 1.2
    mutated_bars = {symbol: mutated.copy() for symbol in base.SYMBOLS}
    changed = strict_build_rows(events, mutated_bars, funding, 12)
    changed_row = changed.iloc[0]
    for column in (
        "decision_reference_price",
        "upper",
        "lower",
        "prior_15m_return",
        "prior_60m_realized_volatility",
        "prior_60m_path_efficiency",
        "distance_to_frozen_upper_60m_liquidity",
        "distance_to_frozen_lower_60m_liquidity",
    ):
        if not np.isclose(float(row[column]), float(changed_row[column]), equal_nan=True):
            raise AssertionError(f"future pre-entry data changed {column}")
    if not bool(changed_row["entry_gap_invalidated"]):
        raise AssertionError("future entry gap was not isolated to execution")
    gap_trade = strict_trade_from_row(
        changed_row,
        0.99,
        24.0,
        mutated,
        funding[str(changed_row["symbol"])],
    )
    if gap_trade is None or gap_trade.exit_reason != "ENTRY_GAP_INVALIDATED_COST_ONLY":
        raise AssertionError(gap_trade)
    if gap_trade.gross_fraction != 0.0:
        raise AssertionError("entry gap produced favorable gross PnL")

    print("strict stablecoin pre-entry causal guard self-test passed")


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
    if args.command == "self-test":
        self_test()
        return 0
    rc = run(args)
    guard = audit_result(args.output)
    print(json.dumps({"strict_causal_guard": guard}, indent=2, sort_keys=True))
    if guard["fatal_validity_violation"]:
        return 2
    result = json.loads((args.output / "RESULT.json").read_text(encoding="utf-8"))
    return 0 if result.get("status") == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1" else 2


if __name__ == "__main__":
    raise SystemExit(main())
