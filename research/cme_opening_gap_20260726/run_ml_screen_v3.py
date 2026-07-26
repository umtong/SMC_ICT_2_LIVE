from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np

import run_ml_screen as base
import run_ml_screen_v2 as purged

ROOT = Path(__file__).resolve().parent
WINNER_AMENDMENT_PATH = ROOT / "amendment_003_positive_winner_count.json"
_ORIGINAL_LOAD_STAGE = base.core.load_stage
_ORIGINAL_TOP_REMOVED_RETURN = base.top_removed_return
_PATCHED = False


def load_stage_with_turnover_alias(*args, **kwargs):
    cme_by_symbol, bars_by_symbol, funding_by_symbol, records = _ORIGINAL_LOAD_STAGE(
        *args, **kwargs
    )
    for symbol, frame in bars_by_symbol.items():
        if "quote_volume" not in frame.columns:
            if "turnover" not in frame.columns:
                raise KeyError(f"{symbol} has neither quote_volume nor turnover")
            frame["quote_volume"] = frame["turnover"]
        if not frame["quote_volume"].equals(frame["turnover"]):
            raise AssertionError(f"{symbol} turnover alias changed values")
    return cme_by_symbol, bars_by_symbol, funding_by_symbol, records


def corrected_top_removed_return(
    values_bps: Iterable[float], fraction: float = 0.10
) -> float:
    """Remove the largest ceil(fraction * positive_count) winners only.

    The registered concentration stress is defined on positive trades, not on
    all trades.  This function preserves the original compounded-return
    semantics while binding the exact corrected count before any successful
    economic output exists.
    """
    values = np.asarray(list(values_bps), dtype=float)
    if not len(values):
        return 0.0
    positive_indices = np.flatnonzero(values > 0)
    if not len(positive_indices):
        return base.compounded_return(values)
    remove_count = max(1, int(math.ceil(len(positive_indices) * fraction)))
    order = positive_indices[np.argsort(values[positive_indices])[::-1]]
    removed = set(int(index) for index in order[:remove_count])
    retained = [value for index, value in enumerate(values) if index not in removed]
    return base.compounded_return(retained)


def load_winner_amendment() -> dict[str, Any]:
    winner = json.loads(WINNER_AMENDMENT_PATH.read_text(encoding="utf-8"))
    core = json.loads(base.AMENDMENT_PATH.read_text(encoding="utf-8"))
    purge = json.loads(purged.PURGE_AMENDMENT_PATH.read_text(encoding="utf-8"))
    if winner["claim_id"] != core["claim_id"]:
        raise ValueError("winner amendment claim mismatch")
    if winner["parent_amendment_id"] != purge["amendment_id"]:
        raise ValueError("winner amendment parent mismatch")
    if winner["market_outcomes_opened_before_amendment"] is not False:
        raise ValueError("winner-count correction was not frozen pre-outcome")
    return winner


def patch_contract() -> None:
    global _PATCHED
    if _PATCHED:
        return
    load_winner_amendment()
    base.core.load_stage = load_stage_with_turnover_alias
    base.top_removed_return = corrected_top_removed_return
    _PATCHED = True


def run(output: Path, cache: Path) -> dict[str, Any]:
    patch_contract()
    winner = load_winner_amendment()
    summary = purged.run(output, cache)
    summary["winner_count_amendment"] = winner["amendment_id"]
    base.write_json(output / "result_summary.json", summary)

    manifest_path = output / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["winner_count_amendment"] = winner["amendment_id"]
    base.write_json(manifest_path, manifest)
    return summary


def self_test() -> None:
    patch_contract()
    purged.self_test()
    import pandas as pd

    index = pd.date_range("2021-01-01T00:00:00Z", periods=3, freq="15min")
    frame = pd.DataFrame(
        {
            "open": [1.0, 1.0, 1.0],
            "high": [1.1, 1.1, 1.1],
            "low": [0.9, 0.9, 0.9],
            "close": [1.0, 1.0, 1.0],
            "volume": [1.0, 1.0, 1.0],
            "turnover": [10.0, 20.0, 30.0],
        },
        index=index,
    )

    def fake_loader(*args, **kwargs):
        return {}, {"BTCUSDT": frame.copy()}, {}, []

    global _ORIGINAL_LOAD_STAGE
    original = _ORIGINAL_LOAD_STAGE
    try:
        _ORIGINAL_LOAD_STAGE = fake_loader
        _, bars, _, _ = load_stage_with_turnover_alias(None, None, None)
        assert "quote_volume" in bars["BTCUSDT"].columns
        assert bars["BTCUSDT"]["quote_volume"].equals(bars["BTCUSDT"]["turnover"])
    finally:
        _ORIGINAL_LOAD_STAGE = original

    # Three positive trades among 100 total must remove one winner, not all
    # three.  The old total-trade count rule would remove up to ten positives.
    values = np.asarray([100.0, 50.0, 25.0] + [-1.0] * 97, dtype=float)
    expected = base.compounded_return([50.0, 25.0] + [-1.0] * 97)
    observed = corrected_top_removed_return(values)
    assert math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-15)
    assert observed > base.compounded_return([-1.0] * 97)
    print("TURNOVER_ALIAS_AND_POSITIVE_WINNER_COUNT_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        run(args.output, args.cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
