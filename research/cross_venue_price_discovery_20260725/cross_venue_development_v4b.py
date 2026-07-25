from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import cross_venue_development_v2 as d2
import cross_venue_development_v3 as d3
import cross_venue_development_v4 as d4

_ORIGINAL_MANDATORY_EXIT = d3.mandatory_exit_price
_PATCHED = False


def strict_exit(row: pd.Series, side: int, quantity: float) -> tuple[float, bool]:
    result = _ORIGINAL_MANDATORY_EXIT(row, side, quantity)
    if result is None:
        raise ValueError("an entered position reached an unusable actual exit quote; fail closed")
    return result


def patch_once() -> None:
    global _PATCHED
    if _PATCHED:
        return
    d3.mandatory_exit_price = strict_exit
    d3.patch_development()
    d2.account_metrics = d4.account_metrics_v4
    _PATCHED = True


def self_test() -> None:
    patch_once()
    patch_once()
    row = pd.Series({
        "bn_bid": 99.9,
        "bn_ask": 100.1,
        "bn_bid_amount": 100.0,
        "bn_ask_amount": 100.0,
    })
    price, overrun = strict_exit(row, 1, 1.0)
    assert price < row.bn_bid and overrun is False
    invalid = pd.Series({
        "bn_bid": float("nan"),
        "bn_ask": 100.1,
        "bn_bid_amount": 0.0,
        "bn_ask_amount": 100.0,
    })
    try:
        strict_exit(invalid, 1, 1.0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid actual exit quote did not fail closed")
    print("cross-venue development V4B self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    patch_once()
    if args.self_test:
        self_test()
        return 0
    result = d2.run(args.pilot_dir, args.output, args.cache)
    result["account_engine_version"] = "4B"
    result["v1_v2_v3_v4_development_promotion_admissible"] = False
    result["drawdown_contract"] = "closed-path drawdown plus maximum per-trade executable-liquidation excursion, capped at 100%"
    result["exit_contract"] = "every entered position exits; unusable actual exit quote fails the run closed"
    result["patch_contract"] = "strict exit and conservative MDD patch applied idempotently once"
    path = args.output / "DEVELOPMENT_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "stage": result["stage"],
        "account_engine_version": "4B",
        "development_gate_pass_count": int(result.get("development_gate_pass_count", 0)),
        "selection_opened": False,
        "2026_opened": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
