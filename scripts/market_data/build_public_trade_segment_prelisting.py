#!/usr/bin/env python3
"""Pre-listing-aware wrapper for official Bybit public trade-flow segments.

Months before the first published trade archive are retained as explicit empty
UTC grids. After the first observed trade, coverage must remain continuous.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

try:
    from . import build_public_trade_month as monthly
    from . import build_public_trade_segment as segment
    from .canonical_spec import SEGMENTS, SYMBOLS, sha256_file
except ImportError:
    import build_public_trade_month as monthly
    import build_public_trade_segment as segment
    from canonical_spec import SEGMENTS, SYMBOLS, sha256_file


def allow_empty_numeric_sanity(frame: pd.DataFrame) -> None:
    if int(frame["observed"].sum()) == 0:
        return
    _ORIGINAL_NUMERIC_SANITY(frame)


def validate_after_first_observation(root: Path, minimum: float) -> dict[str, object]:
    paths = sorted(root.glob("*/trade_bars/1m.parquet"))
    if not paths:
        raise RuntimeError("no monthly 1m files were produced")
    frames = [pd.read_parquet(path, columns=["start_time_ms", "observed"]) for path in paths]
    combined = pd.concat(frames, ignore_index=True).sort_values("start_time_ms")
    observed = combined["observed"].fillna(False).astype(bool)
    count = int(observed.sum())
    if count == 0:
        return {
            "status": "VERIFIED_EMPTY_BEFORE_PUBLIC_ARCHIVE",
            "first_observed_ms": None,
            "last_observed_ms": None,
            "expected_rows_after_first_observed": 0,
            "observed_rows_after_first_observed": 0,
            "coverage_after_first_observed": 0.0,
        }
    first_position = int(observed.to_numpy().nonzero()[0][0])
    last_position = int(observed.to_numpy().nonzero()[0][-1])
    after = observed.iloc[first_position:]
    coverage = float(after.mean())
    if coverage < minimum:
        raise RuntimeError(
            f"coverage after first observed trade {coverage:.9f} below {minimum:.9f}"
        )
    return {
        "status": "VERIFIED_CONTINUOUS_AFTER_FIRST_OBSERVED",
        "first_observed_ms": int(combined.iloc[first_position]["start_time_ms"]),
        "last_observed_ms": int(combined.iloc[last_position]["start_time_ms"]),
        "expected_rows_after_first_observed": int(len(after)),
        "observed_rows_after_first_observed": int(after.sum()),
        "coverage_after_first_observed": coverage,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segment", required=True, choices=sorted(SEGMENTS))
    parser.add_argument("--symbol", required=True, choices=SYMBOLS)
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--chunksize", type=int, default=750_000)
    parser.add_argument("--min-coverage-after-first", type=float, default=0.99)
    args = parser.parse_args()

    monthly.numeric_sanity = allow_empty_numeric_sanity
    build_args = argparse.Namespace(
        segment=args.segment,
        symbol=args.symbol,
        out=args.out,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
        chunksize=args.chunksize,
        min_coverage=0.0,
    )
    output = segment.build(build_args)
    continuity = validate_after_first_observation(output, args.min_coverage_after_first)

    manifest_path = output / "SEGMENT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["prelisting_aware_continuity"] = continuity
    manifest["all_months_verified"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "SEGMENT_MANIFEST.sha256").write_text(
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n", encoding="utf-8"
    )
    print(json.dumps({"status": continuity["status"], "output": str(output)}, indent=2))


_ORIGINAL_NUMERIC_SANITY = monthly.numeric_sanity

if __name__ == "__main__":
    main()
