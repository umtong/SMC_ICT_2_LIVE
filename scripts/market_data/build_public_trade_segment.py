#!/usr/bin/env python3
"""Build one immutable physical segment for one Bybit USDT-linear symbol."""
from __future__ import annotations

import argparse
import json
import shutil
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
    out: list[str] = []
    current = start
    while current < end:
        out.append(f"{current.year:04d}-{current.month:02d}")
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return out


def build(args: argparse.Namespace) -> Path:
    if args.segment not in SEGMENTS:
        raise ValueError(f"unsupported segment {args.segment}")
    if args.symbol not in SYMBOLS:
        raise ValueError(f"unsupported symbol {args.symbol}")
    start_iso, end_iso, logical_segment = SEGMENTS[args.segment]
    root = Path(args.out).resolve()
    final = root / args.segment / args.symbol
    temp_root = root / ".monthly_work" / args.segment / args.symbol
    final.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    month_rows: list[dict[str, object]] = []
    for month in months_between(start_iso, end_iso):
        month_args = Namespace(
            symbol=args.symbol,
            month=month,
            out=str(temp_root),
            timeout=args.timeout,
            max_attempts=args.max_attempts,
            chunksize=args.chunksize,
            min_coverage=args.min_coverage,
        )
        built = monthly.build(month_args)
        verification = verify(built)
        destination = final / month
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(built), destination)
        manifest_path = destination / "DATASET_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        (destination / "VERIFICATION.json").write_text(
            json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        month_rows.append({
            "month": month,
            "dataset_id": manifest["dataset_id"],
            "manifest_sha256": sha256_file(manifest_path),
            "minute_coverage": manifest["coverage"]["minute_coverage"],
            "observed_minutes": manifest["coverage"]["observed_minutes"],
            "missing_minutes": manifest["coverage"]["missing_minutes"],
            "source_raw_bytes": manifest["source_raw_bytes"],
            "source_raw_rows": manifest["source_raw_rows"],
            "relative_path": month,
        })
        print(json.dumps({"month": month, "status": "VERIFIED"}), flush=True)

    shutil.rmtree(root / ".monthly_work", ignore_errors=True)
    manifest = {
        "schema_version": 1,
        "dataset_id": f"DS-BYBIT-LINEAR-{args.symbol}-{args.segment}-TRADEFLOW-V1",
        "dataset_family_id": "DSF-BYBIT-LINEAR-4ASSET-CANONICAL-TRADEFLOW-V1",
        "claim_id": "CLM-20260727-CANONICAL-HALFYEAR-DATA-001",
        "provider": "Bybit official public archive",
        "source_kind": "daily_public_trades_streamed_to_monthly_bars",
        "venue": "Bybit",
        "product": "USDT linear perpetual",
        "symbol": args.symbol,
        "physical_segment": args.segment,
        "logical_segment": logical_segment,
        "start": start_iso,
        "end_exclusive": end_iso,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "months": month_rows,
        "month_count": len(month_rows),
        "all_months_verified": True,
        "total_source_raw_bytes": int(sum(int(row["source_raw_bytes"]) for row in month_rows)),
        "total_source_raw_rows": int(sum(int(row["source_raw_rows"]) for row in month_rows)),
        "total_observed_minutes": int(sum(int(row["observed_minutes"]) for row in month_rows)),
        "total_missing_minutes": int(sum(int(row["missing_minutes"]) for row in month_rows)),
        "causal_availability": (
            "Monthly files are storage partitions only. One-minute bars are visible only after close; "
            "derived bars are visible only after their interval close; missing minutes remain explicit."
        ),
        "credentials_used": False,
        "orders_submitted": False,
    }
    manifest_path = final / "SEGMENT_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (final / "SEGMENT_MANIFEST.sha256").write_text(
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
    parser.add_argument("--min-coverage", type=float, default=0.999)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = build(args)
    print(json.dumps({"status": "BUILT", "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
