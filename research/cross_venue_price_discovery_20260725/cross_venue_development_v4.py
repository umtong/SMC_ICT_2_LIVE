from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import cross_venue_development_v2 as d2
import cross_venue_development_v3 as d3


def strict_mandatory_exit_price(row: pd.Series, side: int, quantity: float) -> tuple[float, bool]:
    result = d3._mandatory_exit_price_v3(row, side, quantity)
    if result is None:
        raise ValueError("an entered position reached an unusable actual exit quote; fail closed")
    return result


def account_metrics_v4(trades: list[d3.AccountTradeV3], state: dict[str, float]) -> dict:
    base = d3.account_metrics_v3(trades, state)
    if not trades:
        base["closed_path_drawdown"] = 0.0
        base["conservative_combined_drawdown"] = 0.0
        return base
    frame = pd.DataFrame([d3.asdict(item) for item in trades])
    nav = np.r_[d2.INITIAL_NAV, frame.nav_after.to_numpy(float)]
    peak = np.maximum.accumulate(nav)
    closed_drawdown = float(np.max(1.0 - nav / np.maximum(peak, 1e-12)))
    intratrade = float(frame.maximum_intratrade_drawdown.max())
    # Conservative upper envelope: a position can begin below the prior account
    # peak and then experience its own adverse excursion. Summing the two avoids
    # understating this interaction when only compact per-trade state is stored.
    combined = min(1.0, closed_drawdown + intratrade)
    base["closed_path_drawdown"] = closed_drawdown
    base["maximum_intratrade_drawdown"] = intratrade
    base["conservative_combined_drawdown"] = combined
    base["maximum_drawdown"] = max(float(base["maximum_drawdown"]), combined)
    return base


def patch_engine() -> None:
    d3._mandatory_exit_price_v3 = d3.mandatory_exit_price
    d3.mandatory_exit_price = strict_mandatory_exit_price
    d3.patch_development()
    d2.account_metrics = account_metrics_v4


def self_test() -> None:
    patch_engine()
    adequate = pd.Series({
        "bn_bid": 99.9,
        "bn_ask": 100.1,
        "bn_bid_amount": 100.0,
        "bn_ask_amount": 100.0,
    })
    price, overrun = strict_mandatory_exit_price(adequate, 1, 1.0)
    assert price < adequate.bn_bid and overrun is False
    invalid = pd.Series({
        "bn_bid": float("nan"),
        "bn_ask": 100.1,
        "bn_bid_amount": 0.0,
        "bn_ask_amount": 100.0,
    })
    try:
        strict_mandatory_exit_price(invalid, 1, 1.0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid exit quote did not fail closed")
    print("cross-venue development V4 self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    patch_engine()
    if args.self_test:
        self_test()
        return 0
    result = d2.run(args.pilot_dir, args.output, args.cache)
    result["account_engine_version"] = 4
    result["v1_v2_v3_development_promotion_admissible"] = False
    result["drawdown_contract"] = "closed-path drawdown plus maximum per-trade executable-liquidation excursion, capped at 100%"
    result["exit_contract"] = "every entered position exits; unusable actual exit quote fails the run closed"
    path = args.output / "DEVELOPMENT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "stage": result["stage"],
        "account_engine_version": 4,
        "development_gate_pass_count": int(result.get("development_gate_pass_count", 0)),
        "selection_opened": False,
        "2026_opened": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
