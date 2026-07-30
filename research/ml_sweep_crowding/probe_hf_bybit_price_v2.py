"""Re-run the immutable 1m price probe at observed contract listing boundaries."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import probe_hf_bybit_price as base


base.STARTS["ETHUSDT"] = pd.Timestamp("2021-03-15T00:00:00Z")


def main() -> int:
    rc = base.main()
    output = Path("research/results/ml_sweep_crowding/bybit_price_mirror_probe.json")
    result = json.loads(output.read_text(encoding="utf-8"))
    result["probe_id"] = "PROBE-20260727-HF-BYBIT-1M-PINNED-002"
    result["listing_boundary_correction"] = {
        "symbol": "ETHUSDT",
        "prior_assumption": "2021-03-01T00:00:00Z",
        "observed_first_timestamp": "2021-03-15T00:00:00Z",
        "reason": "The first probe showed no internal gap: all 20,160 missing minutes were the fourteen days before the mirror's observed ETHUSDT contract start.",
        "economic_outcome_opened_before_correction": False,
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
