#!/usr/bin/env python3
"""Build or index monthly Bybit microbar shards for one physical segment and symbol."""
from __future__ import annotations

import argparse
import json
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import build_public_trade_month as monthly
    from .canonical_spec import SEGMENTS, SYMBOLS, sha256_file
    from .verify_canonical_bybit import verify
except ImportError:  # direct script execution
    import build_public_trade_month as monthly
    from canonical_spec import SEGMENTS, SYMBOLS, sha256_file
    from verify_canonical_bybit import verify


def months_between(start_iso: str, end_iso: str) -> list[str]:
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    result: list[str] = []
    current = start
    while current < end:
        result.append(f"{current.year:04d}-{current.month:02d}")
        current = (
            current.replace(year=current.year + 1, month=1)
            if current.month == 12
            else current.replace(month=current.month + 1)
        )
    return result


def build(args: argparse.Namespace) -> Path:
    if args.segment not in SEGMENTS:
        raise ValueError(f"unsupported segment {args.segment}")
    if args.symbol not in SYMBOLS:
        raise ValueError(f"unsupported symbol {args.symbol}")
    start_iso, end_iso, logical_segment = SEGMENTS[args.segment]
    root = Path(args.out).resolve()
    final = root / args.segment / args.symbol
    final.mkdir(parents=True, exist_ok=True)

    month_rows: list[dict[str, object]] = []
    for month in months_between(start_iso, end_iso):
        month_root = final / month
        if args.index_existing:
            built = month_root
            if not (built / "DATASET_MANIFEST.json").is_file():
                raise FileNotFoundError(f"missing existing month shard: {built}")
        else:
            built = monthly.build(Namespace(
                symbol=args.symbol,
                month=month,
                out=str(root),
                timeout=args.timeout,
                max_attempts=args.max_attempts,
                chunksize=args.chunksize,
            ))
        verification = verify(built)
        manifest_path = built / "DATASET_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        month_rows.append({
            "month": month,
            "dataset_id": manifest["dataset_id"],
            "status": manifest.get("status", "UNKNOWN"),
            "manifest_sha256": sha256_file(manifest_path),
            "relative_path": month,
            "files": [
                {
                    "name": item["name"],
                    "rows": item.get("rows"),
                    "bytes": item.get("bytes"),
                    "sha256": item.get("sha256"),
                }
                for item in manifest.get("files", [])
                if item.get("kind") == "micro_bar"
            ],
            "verification": verification,
        })
        print(json.dumps({"month": month, "status": verification["status"]}), flush=True)

    manifest = {
        "schema_version": 2,
        "dataset_id": f"DS-BYBIT-LINEAR-{args.symbol}-{args.segment}-MICROBAR-V2",
        "dataset_family_id": "DSF-BYBIT-LINEAR-4ASSET-CANONICAL-MICROBAR-V2",
        "claim_id": "CLM-20260727-CANONICAL-HALFYEAR-DATA-001",
        "provider": "Bybit official public archive",
        "venue": "Bybit",
        "product": "USDT linear perpetual",
        "symbol": args.symbol,
        "physical_segment": args.segment,
        "logical_segment": logical_segment,
        "start": start_iso,
        "end_exclusive": end_iso,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stored_intervals": ["1s", "5s", "15s"],
        "derived_interval": "500ms",
        "months": month_rows,
        "month_count": len(month_rows),
        "all_months_verified": all(row["verification"]["status"] == "PASS" for row in month_rows),
        "credentials_used": False,
        "orders_submitted": False,
    }
    manifest_path = final / "MICROBAR_SEGMENT_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (final / "MICROBAR_SEGMENT_MANIFEST.sha256").write_text(
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n", encoding="utf-8"
    )
    return final


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segment", required=True, choices=sorted(SEGMENTS))
    parser.add_argument("--symbol", required=True, choices=SYMBOLS)
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--chunksize", type=int, default=750_000)
    parser.add_argument("--index-existing", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = build(args)
    print(json.dumps({"status": "BUILT", "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
