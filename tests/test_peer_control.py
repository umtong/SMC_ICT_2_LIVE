import csv
import tomllib
from pathlib import Path

from scripts.common import read_jsonl

ROOT = Path(__file__).parents[1]


def test_work_configuration_uses_claims_and_revision_checks():
    project = tomllib.loads((ROOT / "config/project.toml").read_text(encoding="utf-8"))
    workers = tomllib.loads((ROOT / "config/workers.toml").read_text(encoding="utf-8"))
    assert project["state"]["update_protocol"] == "optimistic_revision"
    assert project["data"]["reuse_before_external_search"] is True
    assert workers["work"]["state_update_protocol"] == "optimistic_revision"
    assert workers["defaults"]["check_active_claims"] is True
    assert workers["defaults"]["reuse_registered_artifacts"] is True


def test_work_claim_registry_has_deduplication_fields():
    with (ROOT / "control/work-claims.csv").open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    required = {
        "claim_id",
        "worker_id",
        "objective_fingerprint",
        "scope_fingerprint",
        "base_revision",
        "lease_until",
        "overlap_reason",
    }
    assert required.issubset(header)


def test_reuse_registries_are_parseable_and_uniquely_identified():
    results = read_jsonl(ROOT / "control/result-registry.jsonl")
    attestations = read_jsonl(ROOT / "control/validation-cache.jsonl")

    result_ids = [str(row.get("result_id", "")) for row in results]
    attestation_ids = [str(row.get("attestation_id", "")) for row in attestations]

    assert all(result_ids)
    assert all(attestation_ids)
    assert len(result_ids) == len(set(result_ids))
    assert len(attestation_ids) == len(set(attestation_ids))
