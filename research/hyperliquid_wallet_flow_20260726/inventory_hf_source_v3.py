from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from inventory_hf_source_v2 import main as inventory_v2_main


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output", type=Path, required=True)
    args, _ = parser.parse_known_args()

    original_argv = sys.argv[:]
    try:
        sys.argv = [original_argv[0], "--output", str(args.output)]
        rc = inventory_v2_main()
    finally:
        sys.argv = original_argv
    if rc != 0:
        return rc

    path = args.output / "HF_SOURCE_INVENTORY.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    gate = dict(result["promotion_gate"])
    gate.pop("strategy_pnl_computed", None)
    gate["strategy_pnl_not_computed"] = result["strategy_pnl_computed"] is False
    gate["parquet_or_lz4_rows_not_read"] = result["parquet_or_lz4_rows_read"] is False
    gate["event_json_not_read"] = result["event_json_read"] is False
    result["script_version"] = 3
    result["promotion_gate"] = gate
    result["promotion_gate_passed"] = all(gate.values())
    result["promotion_status"] = (
        "READY_FOR_PRE_2026_DATE_SPECIFIC_PREREGISTRATION"
        if result["promotion_gate_passed"]
        else "SOURCE_COVERAGE_OR_INVENTORY_GATE_FAILED"
    )
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "metadata_sha": result["metadata_sha"],
                "data_file_count": result["data_file_count"],
                "listed_data_bytes_from_tree": result["listed_data_bytes_from_tree"],
                "pre_2026_date_count": result["pre_2026_date_count"],
                "first_explicit_filename_date": result["first_explicit_filename_date"],
                "last_explicit_filename_date": result["last_explicit_filename_date"],
                "promotion_gate": gate,
                "promotion_status": result["promotion_status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
