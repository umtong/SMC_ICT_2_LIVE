from __future__ import annotations

import csv
import json
import tomllib

from common import ROOT, read_jsonl

REQUIRED = [
    "README.md", "AGENTS.md", "config/project.toml", "config/evaluation.toml",
    "config/storage.toml", "config/lanes.toml", "instructions/project-instructions.md",
    "control/current-state.md", "control/champion.json", "control/task-board.csv",
    "data/catalog/source-registry.jsonl", "data/catalog/dataset-registry.jsonl",
    "schemas/source.schema.json", "schemas/run-report.schema.json", "schemas/work-claim.schema.json",
    "docs/parallel-research-mesh.md", ".github/ISSUE_TEMPLATE/work-claim.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
]


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def main() -> int:
    errors=[]
    for rel in REQUIRED:
        if not (ROOT/rel).exists(): fail(f"missing: {rel}",errors)
    try:
        project=tomllib.loads((ROOT/"config/project.toml").read_text(encoding="utf-8"))
        repo=project["github"]["repository"]
        if repo.count("/") != 1: fail("invalid github.repository",errors)
    except Exception as exc: fail(f"project.toml: {exc}",errors)
    parsed={}
    for rel in ["config/evaluation.toml","config/storage.toml","config/lanes.toml"]:
        try: parsed[rel]=tomllib.loads((ROOT/rel).read_text(encoding="utf-8"))
        except Exception as exc: fail(f"{rel}: {exc}",errors)
    storage=parsed.get("config/storage.toml",{})
    if storage:
        policy=storage.get("policy",{})
        if policy.get("public_information_and_materials_usable") is not True:
            fail("storage policy must allow public information and materials",errors)
        if policy.get("separate_storage_permission_review") is not False:
            fail("storage policy must disable separate storage-permission review",errors)
    lanes=parsed.get("config/lanes.toml",{})
    if lanes:
        parallel=lanes.get("parallel",{})
        if parallel.get("coordinator_assignment_gate") is not False:
            fail("parallel research must not require coordinator assignment",errors)
    try:
        champion=json.loads((ROOT/"control/champion.json").read_text(encoding="utf-8"))
        if champion.get("schema_version") != 1: fail("champion schema_version",errors)
    except Exception as exc: fail(f"champion.json: {exc}",errors)
    try:
        rows=read_jsonl(ROOT/"data/catalog/source-registry.jsonl")
        ids=[r.get("source_id") for r in rows]
        urls=[r.get("canonical_url") for r in rows if r.get("canonical_url")]
        hashes=[r.get("sha256") for r in rows if r.get("sha256")]
        if len(ids)!=len(set(ids)): fail("duplicate source_id",errors)
        if len(urls)!=len(set(urls)): fail("duplicate canonical_url",errors)
        if len(hashes)!=len(set(hashes)): fail("duplicate source sha256",errors)
    except Exception as exc: fail(f"source registry: {exc}",errors)
    try:
        with (ROOT/"control/task-board.csv").open(encoding="utf-8",newline="") as f:
            header=next(csv.reader(f))
        if "task_id" not in header or "base_revision" not in header: fail("task-board header",errors)
    except Exception as exc: fail(f"task-board: {exc}",errors)
    runtime=(ROOT/"instructions/project-instructions.md").read_text(encoding="utf-8")
    for forbidden in ["저장 권한을 확인", "classify storage permission", "when permitted"]:
        if forbidden in runtime: fail(f"forbidden runtime storage gate: {forbidden}",errors)
    if (ROOT/"config/project.local.toml").exists():
        fail("config/project.local.toml must not be committed",errors)
    if errors:
        print("VALIDATION FAILED")
        for error in errors: print(f"- {error}")
        return 1
    print("VALIDATION OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
