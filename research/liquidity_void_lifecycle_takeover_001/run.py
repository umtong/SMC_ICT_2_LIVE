#!/usr/bin/env python3
"""Materialize and execute the exact liquidity-void research authority."""
from __future__ import annotations

import base64
import gzip
import hashlib
import os
import sys
from pathlib import Path

AUTHORITY_SHA256 = "9f80cf29b233c181ee569f4c9fa74961d6e00a1855081b6992b07eea49ef638b"
CARRIER_GZIP_SHA256 = "113a4dcd86bbf9544a56a74c3992d88117c1a3d82e169be8b94f71e07f964668"


def main() -> None:
    here = Path(__file__).resolve().parent
    carrier = here / "SOURCE.py.gz.b64"
    compressed = base64.b64decode(carrier.read_text(encoding="utf-8"))
    if hashlib.sha256(compressed).hexdigest() != CARRIER_GZIP_SHA256:
        raise RuntimeError("source carrier gzip SHA-256 mismatch")
    source = gzip.decompress(compressed)
    if hashlib.sha256(source).hexdigest() != AUTHORITY_SHA256:
        raise RuntimeError("materialized authority SHA-256 mismatch")
    target = here / "authority.py"
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != AUTHORITY_SHA256:
        target.write_bytes(source)
    if "--materialize-only" in sys.argv[1:]:
        print(target)
        return
    os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])


if __name__ == "__main__":
    main()
