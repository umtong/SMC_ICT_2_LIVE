from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from common import ROOT

CLAIMS = ROOT / "control/work-claims.csv"
ACTIVE = {"CLAIMED", "RUNNING"}


def normalized(value: str) -> str:
    return " ".join(value.strip().lower().split())


def fingerprint(value: str) -> str:
    return hashlib.sha256(normalized(value).encode("utf-8")).hexdigest()


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_rows() -> tuple[list[str], list[dict[str, str]]]:
    with CLAIMS.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def main() -> int:
    parser = argparse.ArgumentParser(description="Claim an unoccupied research scope")
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--base-revision", required=True, type=int)
    parser.add_argument("--branch", default="")
    parser.add_argument("--lease-hours", type=float, default=8.0)
    parser.add_argument("--overlap-reason", default="")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    objective_fp = fingerprint(args.objective)
    scope_fp = fingerprint(f"{args.objective}\n{args.scope}")
    header, rows = read_rows()

    for row in rows:
        lease = parse_time(row.get("lease_until", ""))
        active = row.get("status") in ACTIVE and lease is not None and lease > now
        if active and row.get("scope_fingerprint") == scope_fp and not args.overlap_reason:
            print(json.dumps({
                "claimed": False,
                "reason": "matching active claim exists",
                "existing_claim_id": row.get("claim_id"),
                "existing_worker_id": row.get("worker_id"),
                "lease_until": row.get("lease_until"),
            }, ensure_ascii=False))
            return 2

    worker_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", args.worker_id).strip("-") or "worker"
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    claim_id = f"CLAIM-{stamp}-{worker_slug}"
    lease_until = now + timedelta(hours=args.lease_hours)
    record = {
        "claim_id": claim_id,
        "worker_id": args.worker_id,
        "objective_fingerprint": objective_fp,
        "scope_fingerprint": scope_fp,
        "base_revision": str(args.base_revision),
        "status": "CLAIMED",
        "started_at": now.isoformat(),
        "lease_until": lease_until.isoformat(),
        "branch": args.branch,
        "pull_request": "",
        "result_id": "",
        "overlap_reason": args.overlap_reason,
        "updated_at": now.isoformat(),
    }
    with CLAIMS.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writerow(record)
    print(json.dumps({"claimed": True, **record}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
