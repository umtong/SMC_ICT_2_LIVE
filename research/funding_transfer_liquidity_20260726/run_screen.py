from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = tuple(sorted(ROOT.glob("implementation.b64.part*")))
EXPECTED_PART_COUNT = 2
EXPECTED_COMPRESSED_SHA256 = "430f9963f6767e250520bdcb10e43cb9b1b40a187f0d779c7f384d9ad0b26abf"
EXPECTED_IMPLEMENTATION_SHA256 = "a5b3b5e41e6697de766ee5b3aef4712401a2350ea3e88a97f07ada57eab636fe"
PATCHED_IMPLEMENTATION_SHA256 = "05917eed3fccacf436885a86c38d5534c55a34dc8d15057caf060e567d334f41"
OLD_DOMAINS = b'DOMAINS = ("https://api.bybit.com", "https://api.bytick.com")'
NEW_DOMAINS = b'''DOMAINS = (
    "https://api.bybit.com",
    "https://api.bytick.com",
    "https://api.bybit.nl",
    "https://api.byhkbit.com",
    "https://api.bybit.tr",
    "https://api.bybit.kz",
    "https://api.bybitgeorgia.ge",
    "https://api.bybit.ae",
    "https://api.bybit.id",
)'''

if len(PARTS) != EXPECTED_PART_COUNT:
    raise RuntimeError(f"implementation part count {len(PARTS)} != {EXPECTED_PART_COUNT}")
encoded = "".join("".join(path.read_text(encoding="utf-8").split()) for path in PARTS)
compressed = base64.b64decode(encoded, validate=True)
if hashlib.sha256(compressed).hexdigest() != EXPECTED_COMPRESSED_SHA256:
    raise RuntimeError("compressed implementation SHA-256 mismatch")
source = gzip.decompress(compressed)
if hashlib.sha256(source).hexdigest() != EXPECTED_IMPLEMENTATION_SHA256:
    raise RuntimeError("scientific implementation SHA-256 mismatch")
if source.count(OLD_DOMAINS) != 1 or NEW_DOMAINS in source:
    raise RuntimeError("unexpected source-transport amendment context")
patched = source.replace(OLD_DOMAINS, NEW_DOMAINS, 1)
if hashlib.sha256(patched).hexdigest() != PATCHED_IMPLEMENTATION_SHA256:
    raise RuntimeError("patched implementation SHA-256 mismatch")
BUNDLED_IMPLEMENTATION_SHA256 = EXPECTED_IMPLEMENTATION_SHA256
BUNDLED_EXECUTED_IMPLEMENTATION_SHA256 = PATCHED_IMPLEMENTATION_SHA256
exec(compile(patched, str(ROOT / "_bundled_implementation.py"), "exec"), globals(), globals())
