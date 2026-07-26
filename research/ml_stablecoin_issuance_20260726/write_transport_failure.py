from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--transport", required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001",
        "transport_id": args.transport,
        "status": "SOURCE_UNAVAILABLE_OR_TRANSPORT_FAILURE",
        "run_exit_code": args.exit_code,
        "conditional_model_screen_authorized": False,
        "market_outcome_opened": False,
        "model_fit": False,
        "trade_or_pnl_opened": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    (args.output / "SOURCE_GATE_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
