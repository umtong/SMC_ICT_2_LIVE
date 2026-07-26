from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

import probe_aws_public_parquet as probe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        result = probe.run_probe(args.output)
    except Exception as exc:
        result = {
            "schema_version": 1,
            "claim_id": probe.CLAIM_ID,
            "transport_id": probe.TRANSPORT_ID,
            "phase": "OUTCOME_SEALED_TRANSPORT_PROBE",
            "provider": "AWS Public Blockchain Data Ethereum logs Parquet",
            "transport_pass": False,
            "scientific_decision": "DO_NOT_USE_AWS_TRANSPORT",
            "fatal_error": repr(exc),
            "traceback": traceback.format_exc(),
            "forbidden_outcome_fields": list(probe.FORBIDDEN_OUTCOME_FIELDS),
            "market_outcome_opened": False,
            "model_fit": False,
            "trade_or_pnl_opened": False,
            "official_2024_2026_opened": False,
            "credentials_used": False,
            "orders_submitted": False
        }
        (args.output / "AWS_TRANSPORT_PROBE_RESULT.json").write_text(
            json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
