from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import run_screen as run


def summarize(path: Path, expected_date: str) -> dict:
    states = run.load_states(path, expected_date)
    source_groups = states.groupby("segment", sort=True)
    source_rows = source_groups.size()
    source_span = source_groups.decision_us.agg(lambda x: (int(x.max()) - int(x.min())) / 1_000_000)
    out = {
        "date": expected_date,
        "state_rows": int(len(states)),
        "source_segments": int(source_rows.size),
        "maximum_source_segment_rows": int(source_rows.max()),
        "maximum_source_segment_span_seconds": float(source_span.max()),
        "source_segments_at_least_120s": int((source_span >= 120).sum()),
        "source_segments_at_least_300s": int((source_span >= 300).sum()),
        "source_segments_at_least_600s": int((source_span >= 600).sum()),
        "bar_diagnostics": {},
    }
    for seconds in run.BAR_SECONDS:
        bars = run.build_bars(states, seconds)
        if bars.empty:
            out["bar_diagnostics"][str(seconds)] = {"bars": 0}
            continue
        sizes = bars.groupby("segment", sort=True).size()
        record = {
            "bars": int(len(bars)),
            "bar_segments": int(len(sizes)),
            "maximum_bars_per_segment": int(sizes.max()),
            "segments_at_least_120s": int((sizes >= int(np.ceil(120 / seconds))).sum()),
            "segments_at_least_300s": int((sizes >= int(np.ceil(300 / seconds))).sum()),
            "segments_at_least_600s": int((sizes >= int(np.ceil(600 / seconds))).sum()),
        }
        raid_counts = {}
        for lookback_seconds in run.LIQUIDITY_LOOKBACK_SECONDS:
            lb = max(3, int(np.ceil(lookback_seconds / seconds)))
            buy = sell = opportunities = 0
            for _, group in bars.groupby("segment", sort=True):
                group = group.sort_values("bar_id").reset_index(drop=True)
                hi = group.high_mid.to_numpy(float)
                lo = group.low_mid.to_numpy(float)
                if len(group) <= lb:
                    continue
                for i in range(lb, len(group)):
                    opportunities += 1
                    prior_high = float(np.max(hi[i-lb:i]))
                    prior_low = float(np.min(lo[i-lb:i]))
                    if hi[i] >= prior_high:
                        buy += 1
                    elif lo[i] <= prior_low:
                        sell += 1
            raid_counts[str(lookback_seconds)] = {
                "eligible_bar_positions": opportunities,
                "zero_excess_buy_side_raids": buy,
                "zero_excess_sell_side_raids": sell,
            }
        record["raid_counts"] = raid_counts
        out["bar_diagnostics"][str(seconds)] = record
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "diagnostic_only": True,
        "rules_or_outcomes_changed": False,
        "fit": summarize(args.fit, run.FIT_DATE),
        "development": summarize(args.development, run.DEVELOPMENT_DATE),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
