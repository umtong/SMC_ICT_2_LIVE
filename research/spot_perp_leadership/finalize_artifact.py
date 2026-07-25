from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finalize(output: Path) -> dict:
    summary_path = output / "result_summary.json"
    audit_path = output / "dataset" / "GAP_AUDIT.json"
    if not summary_path.exists() or not audit_path.exists():
        raise FileNotFoundError("result summary or gap audit is absent")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    loads = audit.get("loads", [])
    if not loads:
        raise AssertionError("gap audit has no source load")
    for load in loads:
        for symbol, funding in load.get("funding", {}).items():
            if funding.get("unvalued_event_count") != 0:
                raise AssertionError(f"{symbol}: unvalued funding event")

    summary["execution_contract"]["funding"] = (
        "official funding calc_time retained for (entry, exit] inclusion; official mark-price open "
        "of the containing UTC minute, with exact same-minute USD-M contract-open fallback only "
        "when that mark observation is absent"
    )
    summary["execution_contract"]["missing_data"] = (
        "regular UTC minute grid; absent source observations remain NaN; no forward fill, "
        "backfill, interpolation, synthetic OHLC or timeline compression; signals and orders "
        "require finite observed inputs"
    )
    summary["gap_audit"] = {
        "path": "dataset/GAP_AUDIT.json",
        "schema_version": audit.get("schema_version"),
        "policy": audit.get("policy"),
        "load_count": len(loads),
        "development_load": loads[0],
    }
    summary["preregistration_amendment"] = "PREREGISTRATION_AMENDMENT_001.json"
    summary["artifact_metadata_finalized"] = True
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    inventory = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "FILE_MANIFEST.sha256":
            inventory.append(f"{sha256_file(path)}  {path.relative_to(output)}")
    (output / "FILE_MANIFEST.sha256").write_text("\n".join(inventory) + "\n", encoding="utf-8")
    print(
        "GAP_SAFE_FINAL_RESULT_JSON="
        + json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False),
        flush=True,
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    finalize(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
