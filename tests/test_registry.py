from pathlib import Path

from scripts.common import canonicalize_url, read_jsonl


def test_youtube_canonicalization():
    assert canonicalize_url("https://youtu.be/abc123?si=x") == "https://www.youtube.com/watch?v=abc123"


def test_initial_registry_is_unique():
    rows = read_jsonl(Path(__file__).parents[1] / "data/catalog/source-registry.jsonl")
    ids = [row["source_id"] for row in rows]
    hashes = [row["sha256"] for row in rows]
    assert len(ids) == len(set(ids))
    assert len(hashes) == len(set(hashes))
