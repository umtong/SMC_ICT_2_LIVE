#!/usr/bin/env python3
"""Materialize the exact inventory captured by transcript run 30218664372."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "PUBLIC_VIDEO_INVENTORY_30218664372.jsonl"
EXPECTED_SHA256 = "4524e2ec92cf05e7fc5dbc61b68c906b30dd4d4fedafa4b0bc861bcdbab604f2"
EXPECTED_COUNTS = {"chartbro": 62, "indicator_sensei": 98, "swipalnam": 26}


def main() -> int:
    chunks = sorted((ROOT / "inventory_payload").glob("inventory.*"))
    if len(chunks) != 4:
        raise RuntimeError(f"expected 4 inventory payload chunks, found {len(chunks)}")
    encoded = b"".join(path.read_bytes().strip() for path in chunks)
    raw = zlib.decompress(base64.b85decode(encoded))
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(f"inventory digest mismatch: {digest}")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    counts = dict(sorted(Counter(row["channel_slug"] for row in rows).items()))
    if counts != EXPECTED_COUNTS:
        raise RuntimeError(f"inventory count mismatch: {counts}")
    ids = [row["video_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate video_id in verified inventory")
    changed = not OUTPUT.exists() or OUTPUT.read_bytes() != raw
    if changed:
        OUTPUT.write_bytes(raw)
    print(json.dumps({
        "output": str(OUTPUT),
        "sha256": digest,
        "rows": len(rows),
        "counts": counts,
        "changed": changed,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
