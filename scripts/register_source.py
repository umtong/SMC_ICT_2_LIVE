from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, append_jsonl, canonicalize_url, read_jsonl, sha256_file

REGISTRY = ROOT / "data/catalog/source-registry.jsonl"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Register one durable source with URL/hash deduplication")
    p.add_argument("--source-id", required=True)
    p.add_argument("--type", required=True, dest="source_type")
    p.add_argument("--url")
    p.add_argument("--file", type=Path)
    p.add_argument("--title")
    p.add_argument("--creator")
    p.add_argument("--language")
    p.add_argument("--drive-path")
    p.add_argument("--status", default="REGISTERED")
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--notes", default="")
    return p


def main() -> int:
    args = parser().parse_args()
    rows = read_jsonl(REGISTRY)
    canonical = canonicalize_url(args.url) if args.url else None
    digest = sha256_file(args.file) if args.file else None
    for row in rows:
        if row.get("source_id") == args.source_id:
            raise SystemExit(f"duplicate source_id: {args.source_id}")
        if canonical and row.get("canonical_url") == canonical:
            raise SystemExit(f"duplicate canonical_url: {canonical}")
        if digest and row.get("sha256") == digest:
            raise SystemExit(f"duplicate sha256: {digest}")
    record = {
        "schema_version": 1,
        "source_id": args.source_id,
        "source_type": args.source_type,
        "canonical_url": canonical,
        "title": args.title,
        "creator": args.creator,
        "language": args.language,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "status": args.status,
        "raw_file_name": args.file.name if args.file else None,
        "raw_drive_path": args.drive_path,
        "sha256": digest,
        "size_bytes": args.file.stat().st_size if args.file else None,
        "tags": args.tag,
        "claims_extracted": False,
        "hypotheses_created": False,
        "notes": args.notes,
    }
    append_jsonl(REGISTRY, record)
    print(args.source_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
