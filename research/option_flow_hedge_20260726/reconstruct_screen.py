from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "screen.py.gz.b64"
PARTS = tuple(ROOT / f"screen.py.gz.b64.part{i:02d}" for i in range(4))
TARGET = ROOT / "screen.py"
EXPECTED = {
    "legacy_base64_sha256": "2f2224ceb7ca760450d9324b1b49957ba5f78fdfb7b95c3dc958394548d9a0ca",
    "legacy_gzip_sha256": "8f078ffa980d2481db47ddbc601791637587063dad599859725c2c2aaa4af6f7",
    "raw_sha256": "a87613b623f0b228ca9a7eb365e2fe462efffd51dbcfa06d1b948061fe5e742d",
    "raw_bytes": 42628,
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalized(path: Path) -> bytes:
    return b"".join(path.read_bytes().split())


def candidate_transports() -> list[tuple[str, bytes]]:
    candidates: list[tuple[str, bytes]] = []
    if SOURCE.is_file():
        candidates.append((SOURCE.name, normalized(SOURCE)))
    if all(part.is_file() for part in PARTS):
        candidates.append(("+".join(part.name for part in PARTS), b"".join(normalized(part) for part in PARTS)))
    return candidates


def main() -> None:
    diagnostics: list[str] = []
    accepted: tuple[str, bytes, bytes, bytes] | None = None

    for name, encoded in candidate_transports():
        transport_sha = sha256(encoded)
        try:
            compressed = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            diagnostics.append(
                f"{name}: transport_bytes={len(encoded)} transport_sha256={transport_sha} decode_error={exc}"
            )
            continue

        gzip_sha = sha256(compressed)
        try:
            raw = gzip.decompress(compressed)
        except OSError as exc:
            diagnostics.append(
                f"{name}: transport_bytes={len(encoded)} transport_sha256={transport_sha} "
                f"gzip_bytes={len(compressed)} gzip_sha256={gzip_sha} decompress_error={exc}"
            )
            continue

        raw_sha = sha256(raw)
        raw_match = len(raw) == EXPECTED["raw_bytes"] and raw_sha == EXPECTED["raw_sha256"]
        diagnostics.append(
            f"{name}: transport_bytes={len(encoded)} transport_sha256={transport_sha} "
            f"legacy_transport_match={transport_sha == EXPECTED['legacy_base64_sha256']} "
            f"gzip_bytes={len(compressed)} gzip_sha256={gzip_sha} "
            f"legacy_gzip_match={gzip_sha == EXPECTED['legacy_gzip_sha256']} "
            f"raw_bytes={len(raw)} raw_sha256={raw_sha} raw_match={raw_match}"
        )

        # The executable Python bytes are the scientific identity. A different
        # deterministic gzip wrapper is transport-only and is accepted only when
        # the exact preregistered raw byte count and SHA-256 both match.
        if raw_match:
            if accepted is not None and accepted[3] != raw:
                raise SystemExit("multiple distinct repository transports matched the frozen raw executable identity")
            accepted = (name, encoded, compressed, raw)

    for line in diagnostics:
        print(f"TRANSPORT_DIAGNOSTIC {line}")
    if accepted is None:
        raise SystemExit("no repository transport matched the frozen raw executable identity")

    name, encoded, compressed, raw = accepted
    compile(raw, str(TARGET), "exec")
    TARGET.write_bytes(raw)
    print(
        f"RECONSTRUCTED {TARGET} transport={name} transport_sha256={sha256(encoded)} "
        f"gzip_sha256={sha256(compressed)} bytes={len(raw)} raw_sha256={sha256(raw)}"
    )


if __name__ == "__main__":
    main()
