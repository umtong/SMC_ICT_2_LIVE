from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, read_jsonl

REGISTRY = ROOT / "control/result-registry.jsonl"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def combined_hash(parts: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Register a reusable research result")
    parser.add_argument("--result-id", required=True)
    parser.add_argument("--claim-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--status", choices=["VALID", "CANDIDATE", "INVALID", "SUPERSEDED"], required=True)
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--dataset-id", action="append", default=[])
    parser.add_argument("--code-commit", default="")
    parser.add_argument("--evaluation-contract", default="config/evaluation.toml")
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()

    artifacts: list[dict[str, str]] = []
    artifact_parts: list[str] = []
    for raw in args.artifact:
        path = (ROOT / raw).resolve()
        try:
            relative = path.relative_to(ROOT)
        except ValueError as exc:
            raise SystemExit(f"artifact outside repository: {raw}") from exc
        if not path.is_file():
            raise SystemExit(f"missing artifact: {raw}")
        digest = file_hash(path)
        artifacts.append({"path": relative.as_posix(), "sha256": digest})
        artifact_parts.append(f"{relative.as_posix()}:{digest}")

    contract_path = ROOT / args.evaluation_contract
    if not contract_path.is_file():
        raise SystemExit(f"missing evaluation contract: {args.evaluation_contract}")
    contract_hash = file_hash(contract_path)
    artifact_fingerprint = combined_hash(artifact_parts) if artifact_parts else combined_hash([args.summary])
    dependency_fingerprint = combined_hash(
        args.source_id + args.dataset_id + [args.code_commit, contract_hash]
    )

    existing = read_jsonl(REGISTRY)
    for row in existing:
        if row.get("result_id") == args.result_id:
            raise SystemExit(f"duplicate result_id: {args.result_id}")
        if (
            row.get("artifact_fingerprint") == artifact_fingerprint
            and row.get("dependency_fingerprint") == dependency_fingerprint
        ):
            print(json.dumps({
                "registered": False,
                "reason": "matching reusable result exists",
                "existing_result_id": row.get("result_id"),
            }, ensure_ascii=False))
            return 2

    record = {
        "schema_version": 1,
        "result_id": args.result_id,
        "claim_id": args.claim_id,
        "worker_id": args.worker_id,
        "status": args.status,
        "summary": args.summary,
        "source_ids": sorted(set(args.source_id)),
        "dataset_ids": sorted(set(args.dataset_id)),
        "code_commit": args.code_commit,
        "evaluation_contract_sha256": contract_hash,
        "artifact_fingerprint": artifact_fingerprint,
        "dependency_fingerprint": dependency_fingerprint,
        "artifacts": artifacts,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with REGISTRY.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"registered": True, **record}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
