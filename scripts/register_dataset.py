from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, append_jsonl, read_jsonl, sha256_file

REGISTRY = ROOT / "data/catalog/dataset-registry.jsonl"


def main() -> int:
    p = argparse.ArgumentParser(description="Register an immutable dataset snapshot")
    p.add_argument("--dataset-id", required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--file", type=Path)
    p.add_argument("--drive-path")
    p.add_argument("--market")
    p.add_argument("--symbols", default="")
    p.add_argument("--timeframe")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--status", default="REGISTERED")
    p.add_argument("--notes", default="")
    args = p.parse_args()
    rows = read_jsonl(REGISTRY)
    digest = sha256_file(args.file) if args.file else None
    if any(row.get("dataset_id") == args.dataset_id for row in rows):
        raise SystemExit(f"duplicate dataset_id: {args.dataset_id}")
    if digest and any(row.get("sha256") == digest for row in rows):
        raise SystemExit(f"duplicate sha256: {digest}")
    append_jsonl(REGISTRY, {
        "schema_version": 1, "dataset_id": args.dataset_id, "provider": args.provider,
        "market": args.market, "symbols": [v for v in args.symbols.split(",") if v],
        "timeframe": args.timeframe, "start": args.start, "end": args.end,
        "registered_at": datetime.now(timezone.utc).isoformat(), "status": args.status,
        "raw_file_name": args.file.name if args.file else None, "raw_drive_path": args.drive_path,
        "sha256": digest, "size_bytes": args.file.stat().st_size if args.file else None,
        "notes": args.notes,
    })
    print(args.dataset_id)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
