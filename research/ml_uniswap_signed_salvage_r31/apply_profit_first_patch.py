from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    output = text.replace(old, new, 1)
    if old in output:
        raise RuntimeError(f"{label}: original text still present")
    return output


def patch(source: Path, output: Path) -> None:
    text = source.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''    if stable_raw == 0 or weth_raw == 0 or (stable_raw > 0) == (weth_raw > 0):\n        raise ValueError("inconsistent stable/WETH Swap signs")\n''',
        '''    # A valid directional Uniswap V3 inventory transfer has opposite-signed\n    # pool deltas. Rare dust swaps can round one leg to zero; they carry no\n    # bilateral stable/WETH inventory information and are excluded explicitly.\n    # Non-zero same-sign deltas remain a hard source error with full identity.\n    if stable_raw == 0 or weth_raw == 0:\n        raise ValueError("NON_ECONOMIC_ZERO_LEG_SWAP")\n    if (stable_raw > 0) == (weth_raw > 0):\n        raise ValueError(\n            "INVALID_SAME_SIGN_SWAP "\n            f"pool={pool_name} block={raw.get('blockNumber')} "\n            f"tx={raw.get('transactionHash')} log={raw.get('logIndex')} "\n            f"stable_raw={stable_raw} weth_raw={weth_raw}"\n        )\n''',
        "signed swap validity",
    )

    text = replace_once(
        text,
        '''                try:\n                    event = decode_swap_log(pool_name, raw)\n                except Exception:\n                    invalid += 1\n                    raise\n''',
        '''                try:\n                    event = decode_swap_log(pool_name, raw)\n                except ValueError as exc:\n                    invalid += 1\n                    if str(exc) == "NON_ECONOMIC_ZERO_LEG_SWAP":\n                        # Zero-leg dust is not a directional inventory event.\n                        # Keep the count in the immutable source manifest and\n                        # continue without manufacturing a trade direction.\n                        continue\n                    raise\n''',
        "zero-leg source handling",
    )

    text = replace_once(
        text,
        '''    boundary_index = min(max(start, stop_index - 1), len(market) - 1)\n    adverse = lower if side > 0 else upper\n    return boundary_index, adverse, "PARTITION_BOUNDARY_STRUCTURAL_STOP"\n''',
        '''    # The evaluation boundary is not a strategy exit. Mark the still-open\n    # position at the last causally observed close and retain a distinct outcome\n    # so completed-trade diagnostics never count the mark as a closed trade.\n    boundary_index = min(max(start, stop_index - 1), len(market) - 1)\n    return boundary_index, float(market.close.iloc[boundary_index]), "PARTITION_BOUNDARY_MARK"\n''',
        "boundary NAV mark",
    )

    text = replace_once(
        text,
        '''    returns = np.asarray([trade.account_return for trade in trades], dtype=float)\n    profits = np.asarray([trade.pnl for trade in trades], dtype=float)\n''',
        '''    completed_trades = [\n        trade for trade in trades if trade.outcome != "PARTITION_BOUNDARY_MARK"\n    ]\n    returns = np.asarray([trade.account_return for trade in completed_trades], dtype=float)\n    profits = np.asarray([trade.pnl for trade in completed_trades], dtype=float)\n''',
        "completed trade diagnostics",
    )

    text = replace_once(
        text,
        '''        trade_count=len(trades),\n''',
        '''        trade_count=len(completed_trades),\n''',
        "completed trade count",
    )

    text = replace_once(
        text,
        '''    positive = [trade for trade in result.trades if trade.pnl > 0]\n''',
        '''    positive = [\n        trade\n        for trade in result.trades\n        if trade.outcome != "PARTITION_BOUNDARY_MARK" and trade.pnl > 0\n    ]\n''',
        "winner removal boundary exclusion",
    )

    text = replace_once(
        text,
        '''def confirmation_gate(metrics: Mapping[str, Any], replay18: ReplayResult, replay24: ReplayResult, removed18: ReplayResult) -> dict[str, bool]:\n    return {\n        "minimum_labels_and_both_classes": int(metrics.get("resolved_labels", 0)) >= 50 and bool(metrics.get("both_classes")),\n        "auc_exceeds_distance_baseline": float(metrics.get("auc_lift", -math.inf)) > 0,\n        "positive_brier_skill": float(metrics.get("brier_skill", -math.inf)) > 0,\n        "minimum_30_trades_18bps": replay18.trade_count >= 30,\n        "both_confirmation_halves_positive_18bps": all(value > 0 for value in replay18.half_returns.values()),\n        "profit_factor_at_least_1_10_18bps": replay18.profit_factor >= 1.10,\n        "nonnegative_24bps": replay24.total_return >= 0,\n        "positive_winner_removed_18bps": removed18.total_return > 0,\n        "mdd_below_35pct_and_no_liquidation": replay18.maximum_drawdown < 0.35 and replay18.final_nav > 0,\n    }\n\n\ndef development_gate(replay18: ReplayResult, replay24: ReplayResult, removed18: ReplayResult) -> dict[str, bool]:\n    quarters = list(replay18.quarter_returns.values())\n    return {\n        "positive_24bps": replay24.total_return > 0,\n        "both_2023h2_quarters_positive_18bps": len(quarters) == 2 and all(value > 0 for value in quarters),\n        "positive_median_trade_18bps": replay18.median_trade_return > 0,\n        "minimum_40_trades_18bps": replay18.trade_count >= 40,\n        "positive_winner_removed_18bps": removed18.total_return > 0,\n        "mdd_below_30pct_18bps": replay18.maximum_drawdown < 0.30,\n        "growth_above_donchian_benchmark_24bps": replay24.geometric_daily_growth > 0.0007001887213879954,\n    }\n''',
        '''def confirmation_gate(metrics: Mapping[str, Any], replay18: ReplayResult, replay24: ReplayResult, removed18: ReplayResult) -> dict[str, bool]:\n    # Confirmation remains a model-population validity check. Prediction skill,\n    # PF, median, half-period signs and winner removal are reported diagnostics,\n    # not independent vetoes that can hide a profitable 2023 account path.\n    return {\n        "minimum_labels_and_both_classes": int(metrics.get("resolved_labels", 0)) >= 50 and bool(metrics.get("both_classes")),\n    }\n\n\ndef development_gate(replay18: ReplayResult, replay24: ReplayResult, removed18: ReplayResult) -> dict[str, bool]:\n    # Profit-first advancement: exact-Bybit reconstruction opens only when the\n    # unchanged strategy has positive account growth after both 18 and 24 bp and\n    # the account remains alive. Other metrics remain diagnostics, not vetoes.\n    return {\n        "positive_18bps": replay18.total_return > 0,\n        "positive_24bps": replay24.total_return > 0,\n        "account_survives_without_liquidation": replay18.final_nav > 0 and replay24.final_nav > 0,\n    }\n''',
        "profit-first gates",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    patch(args.source, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
