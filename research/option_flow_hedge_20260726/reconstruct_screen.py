from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "screen.py.gz.b64"
PARTS = tuple(ROOT / f"screen.py.gz.b64.part{i:02d}" for i in range(4))
TARGET = ROOT / "screen.py"
EXPECTED = {
    "base64_sha256": "2f2224ceb7ca760450d9324b1b49957ba5f78fdfb7b95c3dc958394548d9a0ca",
    "gzip_sha256": "8f078ffa980d2481db47ddbc601791637587063dad599859725c2c2aaa4af6f7",
    "raw_sha256": "a87613b623f0b228ca9a7eb365e2fe462efffd51dbcfa06d1b948061fe5e742d",
    "raw_bytes": 42628,
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalized(path: Path) -> bytes:
    return b"".join(path.read_bytes().split())


def main() -> None:
    single = normalized(SOURCE)
    if sha256(single) == EXPECTED["base64_sha256"]:
        encoded = single
        transport = str(SOURCE.name)
    else:
        missing = [str(part.name) for part in PARTS if not part.is_file()]
        if missing:
            raise SystemExit(
                f"base64 transport checksum mismatch and split transport missing: {missing}"
            )
        split = b"".join(normalized(part) for part in PARTS)
        if sha256(split) != EXPECTED["base64_sha256"]:
            raise SystemExit(
                "base64 transport checksum mismatch for both single and split transports"
            )
        encoded = split
        transport = "+".join(part.name for part in PARTS)

    compressed = base64.b64decode(encoded, validate=True)
    if sha256(compressed) != EXPECTED["gzip_sha256"]:
        raise SystemExit("gzip checksum mismatch")
    raw = gzip.decompress(compressed)
    if len(raw) != EXPECTED["raw_bytes"] or sha256(raw) != EXPECTED["raw_sha256"]:
        raise SystemExit("reconstructed screen checksum mismatch")
    compile(raw, str(TARGET), "exec")
    TARGET.write_bytes(raw)
    print(
        f"RECONSTRUCTED {TARGET} transport={transport} "
        f"bytes={len(raw)} sha256={sha256(raw)}"
    )


if __name__ == "__main__":
    main()
