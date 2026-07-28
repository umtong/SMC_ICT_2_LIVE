#!/usr/bin/env python3
"""Materialize the independently authored SCLD source from hash-pinned payload parts."""
from __future__ import annotations

import argparse
import base64
import hashlib
import zlib
from pathlib import Path

EXPECTED_SHA256 = "915aa754db20da992f37c51aadd058f5fad13151b5d6efb0fc459882b39fe498"
EXPECTED_PARTS = 6


def materialize(output: Path) -> None:
    payload_root = Path(__file__).resolve().parent / "source_payload"
    parts = sorted(payload_root.glob("part*.txt"))
    if len(parts) != EXPECTED_PARTS:
        raise RuntimeError(f"expected {EXPECTED_PARTS} payload parts; found {len(parts)}")
    payload = "".join(path.read_text(encoding="ascii").strip() for path in parts)
    data = zlib.decompress(base64.b64decode(payload.encode("ascii")))
    actual = hashlib.sha256(data).hexdigest()
    if actual != EXPECTED_SHA256:
        raise RuntimeError(f"source payload hash mismatch: {actual}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    print(f"materialized {output} sha256={actual} bytes={len(data)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    materialize(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
