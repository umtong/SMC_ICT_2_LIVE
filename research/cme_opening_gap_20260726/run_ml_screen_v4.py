from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

import run_ml_screen as base
import run_ml_screen_v3 as corrected_source

WINNER_AMENDMENT_PATH = (
    Path(__file__).resolve().parent / "amendment_003_positive_winner_count.json"
)
_PATCHED = False


def top_positive_removed_return(
    values_bps: np.ndarray,
    fraction: float = 0.10,
) -> float:
    values = np.asarray(values_bps, dtype=float)
    if not len(values):
        return 0.0
    positive_indices = np.flatnonzero(values > 0)
    if not len(positive_indices):
        return base.compounded_return(values)
    count = max(1, int(math.ceil(len(positive_indices) * fraction)))
    order = positive_indices[np.argsort(values[positive_indices])[::-1]]
    removed = set(int(index) for index in order[:count])
    retained = [value for index, value in enumerate(values) if index not in removed]
    return base.compounded_return(retained)


def patch_metric() -> None:
    global _PATCHED
    if _PATCHED:
        return
    amendment = json.loads(WINNER_AMENDMENT_PATH.read_text(encoding="utf-8"))
    if amendment["claim_id"] != json.loads(
        base.PREREG_PATH.read_text(encoding="utf-8")
    )["claim_id"]:
        raise ValueError("winner-removal amendment claim mismatch")
    base.top_removed_return = top_positive_removed_return
    _PATCHED = True


def run(output: Path, cache: Path) -> dict[str, Any]:
    corrected_source.patch_loader()
    patch_metric()
    result = corrected_source.purged.run(output, cache)
    result["winner_removal_amendment"] = json.loads(
        WINNER_AMENDMENT_PATH.read_text(encoding="utf-8")
    )["amendment_id"]
    base.write_json(output / "result_summary.json", result)
    return result


def self_test() -> None:
    corrected_source.self_test()
    patch_metric()
    values = np.asarray(list(range(1, 21)) + [-1.0] * 80, dtype=float)
    observed = top_positive_removed_return(values, 0.10)
    expected_values = [
        value
        for index, value in enumerate(values)
        if index not in {18, 19}
    ]
    expected = base.compounded_return(expected_values)
    assert math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-15)
    over_removed_values = [
        value
        for index, value in enumerate(values)
        if index not in set(range(10, 20))
    ]
    over_removed = base.compounded_return(over_removed_values)
    assert not math.isclose(observed, over_removed, rel_tol=0.0, abs_tol=1e-15)
    assert base.top_removed_return is top_positive_removed_return
    print("TOP_POSITIVE_WINNER_COUNT_SELF_TEST_PASS")


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
