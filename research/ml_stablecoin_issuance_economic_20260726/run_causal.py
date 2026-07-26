from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run as base

ENGINE = "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_CAUSAL_V2"
ORIGINAL_REPLAY = base.replay


def build_rows(
    events: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    delay: int = 12,
) -> pd.DataFrame:
    """Build rows using only completed information available before entry open."""
    del funding
    if delay not in (12, 64):
        raise ValueError("delay must be 12 or 64")
    events = events.reset_index(drop=True).copy()
    event_time_col = f"available_timestamp_{delay}"
    signed = np.where(
        events["direction"].astype(str).str.upper().eq("MINT"), 1.0, -1.0
    )
    event_seconds = events[event_time_col].to_numpy(np.int64)
    amount = events["amount_usd"].to_numpy(float)
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
            float(amount[left60:i][same_mask].sum()) if i > left60 else 0.0
        )
        prior_net[i] = (
            float(np.sum(amount[left24:i] * signed[left24:i]))
            if i > left24
            else 0.0
        )

    feats = {symbol: base._returns_features(frame) for symbol, frame in bars.items()}
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
            j = base._index_at_or_after(times, next_open_ms)
            if j is None or j < 61:
                continue
            completed_index = j - 1
            entry = float(frame.iloc[j]["open"])
            # These shifted levels are known at the entry open and contain bars <= j-1.
            upper = float(feats[symbol]["prior_high"][j])
            lower = float(feats[symbol]["prior_low"][j])
            if not (
                np.isfinite(upper)
                and np.isfinite(lower)
                and upper > entry > lower > 0
            ):
                continue

            # Return, volatility, efficiency and breadth must use the last completed
            # minute. Reading index j would include the future close of the entry bar.
            ret15 = float(feats[symbol]["ret15"][completed_index])
            vol60 = float(feats[symbol]["vol60"][completed_index])
            eff60 = float(feats[symbol]["eff60"][completed_index])
            per_event_ret15[event_id][symbol] = ret15
            upper_dist = upper / entry - 1.0
            lower_dist = 1.0 - lower / entry

            boundary = base.label_boundary_ms(decision_ms)
            boundary_index = int(np.searchsorted(times, boundary, side="left")) - 1
            if boundary_index < j:
                continue
            exit_index = boundary_index
            label = np.nan
            ambiguous = False
            reason = "UNRESOLVED_AT_STAGE_BOUNDARY"
            for k in range(j, boundary_index + 1):
                hi = float(frame.iloc[k]["high"])
                lo = float(frame.iloc[k]["low"])
                hit_up = hi >= upper
                hit_down = lo <= lower
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
                    "entry_index": j,
                    "completed_feature_index": completed_index,
                    "entry_ms": int(times[j]),
                    "exit_index": exit_index,
                    "exit_ms": int(times[exit_index]),
                    "stage_boundary_ms": int(boundary),
                    "entry": entry,
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
                    "distance_to_frozen_upper_60m_liquidity": upper_dist,
                    "distance_to_frozen_lower_60m_liquidity": lower_dist,
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    breadth: dict[str, float] = {}
    for event_id, item in per_event_ret15.items():
        vals = [item.get(symbol, np.nan) for symbol in base.SYMBOLS]
        finite = [value for value in vals if np.isfinite(value)]
        breadth[event_id] = (
            float(np.mean(np.sign(finite))) if finite else float("nan")
        )
    out["btc_eth_completed_return_breadth"] = out["event_id"].map(breadth)
    return out.sort_values(["decision_ms", "event_id", "symbol"]).reset_index(
        drop=True
    )


def trade_from_row(
    row: pd.Series,
    p_up: float,
    cost_bps: float,
    bars: pd.DataFrame,
    funding: pd.DataFrame,
) -> base.Trade | None:
    """Create a structural trade; unresolved paths are marked, never clock-closed."""
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
    entry = float(row["entry"])
    upper = float(row["upper"])
    lower = float(row["lower"])
    entry_index = int(row["entry_index"])
    end_index = int(row["exit_index"])
    ambiguous = False
    resolved = False
    reason = "MARK_TO_MARKET_STAGE_BOUNDARY"
    exit_price = float(bars.iloc[end_index]["close"])

    for k in range(entry_index, end_index + 1):
        rec = bars.iloc[k]
        op = float(rec["open"])
        hi = float(rec["high"])
        lo = float(rec["low"])
        hit_target = hi >= upper if side == 1 else lo <= lower
        hit_stop = lo <= lower if side == 1 else hi >= upper
        if hit_target and hit_stop:
            ambiguous = True
            resolved = True
            reason = "STOP_FIRST_AMBIGUOUS"
            exit_price = min(lower, op) if side == 1 else max(upper, op)
            end_index = k
            break
        if hit_stop:
            resolved = True
            reason = "STOP"
            exit_price = min(lower, op) if side == 1 else max(upper, op)
            end_index = k
            break
        if hit_target:
            resolved = True
            reason = "TARGET"
            exit_price = upper if side == 1 else lower
            end_index = k
            break

    if resolved:
        exit_ms = int(bars.iloc[end_index]["open_time_ms"])
    else:
        # Value the still-open position at the last completed close. The cost path
        # includes hypothetical exit cost in NAV, but no strategy close is asserted.
        exit_price = float(bars.iloc[end_index]["close"])
        exit_ms = int(
            row.get(
                "stage_boundary_ms",
                int(bars.iloc[end_index]["open_time_ms"]) + 60_000,
            )
        )

    gross = side * (exit_price / entry - 1.0)
    funding_fraction = base._funding_fraction(
        funding,
        bars,
        int(row["entry_ms"]),
        exit_ms,
        entry,
        side,
    )
    stop_fraction = lower_distance if side == 1 else upper_distance
    return base.Trade(
        event_id=str(row["event_id"]),
        symbol=str(row["symbol"]),
        decision_ms=int(row["decision_ms"]),
        entry_ms=int(row["entry_ms"]),
        exit_ms=exit_ms,
        side=side,
        entry=entry,
        exit_price=exit_price,
        stop_price=lower if side == 1 else upper,
        target_price=upper if side == 1 else lower,
        stop_fraction=stop_fraction,
        gross_fraction=float(gross),
        funding_fraction=float(funding_fraction),
        model_probability_up=float(p_up),
        ev_bps=float(max(ev_long, ev_short) * 10_000.0),
        exit_reason=reason,
        ambiguous=ambiguous,
    )


def replay(*args: Any, **kwargs: Any) -> dict[str, Any]:
    result = ORIGINAL_REPLAY(*args, **kwargs)
    result["boundary_mark_count"] = sum(
        row.get("exit_reason") == "MARK_TO_MARKET_STAGE_BOUNDARY"
        for row in result.get("ledger", [])
    )
    result["forced_boundary_close"] = False
    return result


def development_gate(result: dict[str, Any]) -> dict[str, bool]:
    """Advancement contract from amendment 004; other metrics remain diagnostics."""
    metrics = result["costs"]["24"]
    positive = float(metrics["total_return"]) > 0
    no_liquidation = not bool(metrics["liquidation"])
    gate = {
        "positive_calendar_2023_total_return_at_24bps": positive,
        "no_forced_liquidation_or_bankruptcy": no_liquidation,
    }
    gate["all"] = all(gate.values())
    return gate


def risk_search(
    rows: pd.DataFrame,
    probs: np.ndarray,
    bars: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    risks = (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.30, 0.60)
    caps = (1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 35.0, 50.0, 75.0, 100.0)
    trades = base.route(rows, probs, bars, funding, base.PRIMARY_COST_BPS)
    candidates: list[dict[str, Any]] = []
    for risk in risks:
        for cap in caps:
            metrics = base.replay(
                trades,
                base.PRIMARY_COST_BPS,
                "2023-01-01",
                "2024-01-01",
                risk,
                cap,
            )
            winner_removed, excluded = base.winner_removed(
                rows,
                probs,
                bars,
                funding,
                base.PRIMARY_COST_BPS,
                "2023-01-01",
                "2024-01-01",
                risk,
                cap,
            )
            candidates.append(
                {
                    "risk": risk,
                    "notional_cap": cap,
                    "growth": metrics["geometric_calendar_day_growth"],
                    "return": metrics["total_return"],
                    "mdd": metrics["maximum_drawdown"],
                    "liquidation": metrics["liquidation"],
                    "boundary_mark_count": metrics["boundary_mark_count"],
                    "winner_removed_growth": winner_removed[
                        "geometric_calendar_day_growth"
                    ],
                    "winner_removed_return": winner_removed["total_return"],
                    "removed_event_ids": excluded,
                }
            )
    eligible = [
        candidate
        for candidate in candidates
        if not candidate["liquidation"] and candidate["growth"] > 0
    ]
    selected = (
        max(
            eligible,
            key=lambda candidate: (
                candidate["growth"],
                candidate["winner_removed_growth"],
                -candidate["mdd"],
            ),
        )
        if eligible
        else None
    )
    return {
        "candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "selection_rule": "highest positive 24bp growth among no-liquidation paths",
        "selected": selected,
        "candidates": candidates,
    }


# Route/evaluation helpers in the base module resolve these names at runtime.
base.trade_from_row = trade_from_row
base.replay = replay


def run(args: argparse.Namespace) -> int:
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    events = base.load_events(args.events)
    if any(
        pd.to_datetime(events["block_timestamp"], unit="s", utc=True).dt.year
        >= 2024
    ):
        raise AssertionError("pre-2024 stage received 2024 event")

    base.acquire_binance(args.market_cache, "2020-12", "2023-12")
    bars, funding = base.load_market(args.market_cache, "2020-12", "2023-12")
    rows12 = build_rows(events, bars, funding, 12)
    rows64 = build_rows(events, bars, funding, 64)
    if rows12.empty:
        raise RuntimeError("no economically evaluable rows")

    model, calibrator, median_map, medians = base.fit_model(rows12)
    probabilities12 = base.probabilities(model, calibrator, medians, rows12)
    probabilities64 = (
        base.probabilities(model, calibrator, medians, rows64)
        if not rows64.empty
        else np.array([], dtype=float)
    )
    probability_map12 = dict(zip(rows12.index.to_list(), probabilities12.tolist()))

    confirmation_rows = base.segment(rows12, "2022-07-01", "2023-01-01")
    confirmation_probabilities = np.array(
        [probability_map12[index] for index in confirmation_rows.index], dtype=float
    )
    confirmation = base.evaluate_stage(
        "2022H2_CONFIRMATION_12_BLOCK",
        confirmation_rows,
        confirmation_probabilities,
        bars,
        funding,
        "2022-07-01",
        "2023-01-01",
    )
    confirmation_diagnostics = base.confirmation_gate(confirmation)
    confirmation_diagnostics["all_diagnostics"] = all(
        confirmation_diagnostics.values()
    )

    stress = None
    if not rows64.empty:
        probability_map64 = dict(
            zip(rows64.index.to_list(), probabilities64.tolist())
        )
        confirmation64 = base.segment(rows64, "2022-07-01", "2023-01-01")
        probabilities_confirmation64 = np.array(
            [probability_map64[index] for index in confirmation64.index],
            dtype=float,
        )
        stress = base.evaluate_stage(
            "2022H2_CONFIRMATION_64_BLOCK_STRESS",
            confirmation64,
            probabilities_confirmation64,
            bars,
            funding,
            "2022-07-01",
            "2023-01-01",
        )

    development_rows = base.segment(rows12, "2023-01-01", "2024-01-01")
    development_probabilities = np.array(
        [probability_map12[index] for index in development_rows.index], dtype=float
    )
    development = base.evaluate_stage(
        "2023_DEVELOPMENT",
        development_rows,
        development_probabilities,
        bars,
        funding,
        "2023-01-01",
        "2024-01-01",
    )
    advancement = development_gate(development)
    risk = None
    if advancement["all"]:
        risk = risk_search(
            development_rows,
            development_probabilities,
            bars,
            funding,
        )
        advancement["risk_search_survivor"] = risk["selected"] is not None
        advancement["all"] = all(
            value for key, value in advancement.items() if key != "all"
        )

    status = (
        "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
        if advancement.get("all")
        else "PRE2024_BELOW_GATE"
    )
    result: dict[str, Any] = {
        "schema_version": 1,
        "claim_id": base.CLAIM_ID,
        "engine": ENGINE,
        "hard_validity_correction": (
            "CORRECTION-20260726-ML-STABLECOIN-CAUSAL-FEATURE-BOUNDARY-MARK-006"
        ),
        "status": status,
        "source_event_count": int(len(events)),
        "row_count_12": int(len(rows12)),
        "row_count_64": int(len(rows64)),
        "feature_names": list(base.FEATURES),
        "feature_medians": median_map,
        "model": {
            "family": "HistGradientBoostingClassifier",
            "isotonic": calibrator is not None,
        },
        "confirmation": confirmation,
        "confirmation_diagnostics_not_advancement_vetoes": confirmation_diagnostics,
        "confirmation_64_block_stress_diagnostic": stress,
        "development_opened": True,
        "development": development,
        "development_gate": advancement,
        "risk_search": risk,
        "official_2024h1_opened": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }

    def strip_ledgers(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: strip_ledgers(item)
                for key, item in value.items()
                if key not in {"trade_ledger", "candidates"}
            }
        if isinstance(value, list):
            return [strip_ledgers(item) for item in value]
        return value

    compact = strip_ledgers(result)
    (output / "RESULT.json").write_text(
        json.dumps(
            base.json_safe(compact),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    rows12.to_parquet(output / "EVENT_ROWS_12.parquet", index=False)
    if not rows64.empty:
        rows64.to_parquet(output / "EVENT_ROWS_64.parquet", index=False)
    (output / "FULL_RESULT.json").write_text(
        json.dumps(
            base.json_safe(result),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
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
    print(
        json.dumps(
            base.json_safe(compact),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0 if advancement.get("all") else 2


def self_test() -> None:
    base.self_test()
    amendment_grid_size = 9 * 11
    assert amendment_grid_size == 99
    positive_only = {
        "costs": {
            "24": {
                "total_return": 0.01,
                "liquidation": False,
                "median_trade_bps": -100.0,
                "profit_factor": 0.5,
                "winner_removed": {"total_return": -0.1},
                "first_half_return": -0.2,
                "second_half_return": 0.3,
            }
        }
    }
    assert development_gate(positive_only)["all"] is True
    print("causal correction self-test passed")


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
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
