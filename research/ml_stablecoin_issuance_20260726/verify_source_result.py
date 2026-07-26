from __future__ import annotations

import argparse
import json
from pathlib import Path

ALLOWED = {
    "PASS",
    "FAIL_BELOW_SOURCE_DENSITY_OR_COVERAGE",
    "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("transport")
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    assert result["claim_id"] == "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
    assert result["transport_id"] == args.transport
    assert result["status"] in ALLOWED
    assert result["market_outcome_opened"] is False
    assert result["model_fit"] is False
    assert result["trade_or_pnl_opened"] is False
    assert result["official_2024_2026_opened"] is False
    assert result["orders_submitted"] is False
    print(json.dumps({
        "status": result["status"],
        "events": result.get("event_count"),
        "model_authorized": result["conditional_model_screen_authorized"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
