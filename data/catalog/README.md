# Catalogs

- `source-registry.jsonl`: one JSON object per external or user-provided source.
- `dataset-registry.jsonl`: one JSON object per market/reference dataset or immutable snapshot.
- `entity-registry.jsonl`: reusable people, channels, organizations, exchanges, and repositories.

Registries contain metadata and provenance, not unsupported success claims. Use `scripts/register_source.py` and `scripts/register_dataset.py` to prevent duplicate entries.
