from pathlib import Path

from scripts.common import canonicalize_url, read_jsonl


def test_youtube_canonicalization():
    assert canonicalize_url("https://youtu.be/abc123?si=x") == "https://www.youtube.com/watch?v=abc123"


def test_source_registry_non_null_identifiers_are_unique():
    rows = read_jsonl(Path(__file__).parents[1] / "data/catalog/source-registry.jsonl")
    ids = [str(row["source_id"]) for row in rows if row.get("source_id")]
    hashes = [str(row["sha256"]) for row in rows if row.get("sha256")]

    assert len(ids) == len(set(ids))
    assert len(hashes) == len(set(hashes))
