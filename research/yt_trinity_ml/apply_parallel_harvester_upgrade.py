#!/usr/bin/env python3
"""Materialize the checkpointed parallel transcript harvester from small payload chunks."""

from __future__ import annotations

import base64
import hashlib
import json
import py_compile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SPECS = (
    {
        "name": "harvest",
        "pattern": "harvest.*",
        "output": ROOT / "harvest_transcripts.py",
        "sha256": "b1add0e66a0df2dbd5ae40d2cd92115b51444b3439cd4040bac4f86fd37ed2a1",
    },
    {
        "name": "merge",
        "pattern": "merge.*",
        "output": ROOT / "merge_corpora.py",
        "sha256": "8638387f64a3800ffe5f3a2caf05984be4c7d550661d9cccd7fc43d10a8c6e86",
    },
)


def materialize(spec: dict[str, object]) -> dict[str, object]:
    chunk_root = ROOT / "upgrade_chunks"
    paths = sorted(chunk_root.glob(str(spec["pattern"])))
    if not paths:
        raise RuntimeError(f"no payload chunks for {spec['name']}")
    encoded = b"".join(path.read_bytes().strip() for path in paths)
    raw = zlib.decompress(base64.b85decode(encoded))
    digest = hashlib.sha256(raw).hexdigest()
    expected = str(spec["sha256"])
    if digest != expected:
        raise RuntimeError(f"{spec['name']} digest mismatch: {digest} != {expected}")
    output = Path(spec["output"])
    changed = not output.exists() or output.read_bytes() != raw
    if changed:
        output.write_bytes(raw)
    py_compile.compile(str(output), doraise=True)
    return {
        "name": spec["name"],
        "output": str(output.relative_to(ROOT.parent.parent)),
        "chunks": [path.name for path in paths],
        "bytes": len(raw),
        "sha256": digest,
        "changed": changed,
    }


def main() -> int:
    results = [materialize(spec) for spec in SPECS]
    print(json.dumps({"schema_version": 1, "files": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
