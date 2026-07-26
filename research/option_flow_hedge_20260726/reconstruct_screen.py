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


def split_base64_members(encoded: bytes) -> list[bytes]:
    """Recover mechanically concatenated padded Base64 members.

    A valid Base64 member may end in one or two '=' bytes. The repository's
    legacy transport can contain another member immediately after that padding.
    Each member is decoded strictly and only the decoded byte streams are joined.
    """

    members: list[bytes] = []
    start = 0
    index = 0
    while index < len(encoded):
        if encoded[index] != ord("="):
            index += 1
            continue
        end = index + 1
        while end < len(encoded) and encoded[end] == ord("="):
            end += 1
        segment = encoded[start:end]
        if len(segment) % 4 == 0:
            try:
                decoded = base64.b64decode(segment, validate=True)
            except (binascii.Error, ValueError):
                pass
            else:
                members.append(decoded)
                start = end
        index = end

    if start < len(encoded):
        tail = encoded[start:]
        if len(tail) % 4 != 0:
            raise ValueError(f"trailing Base64 member length is not divisible by four: {len(tail)}")
        members.append(base64.b64decode(tail, validate=True))

    if len(members) < 2:
        raise ValueError("transport did not contain multiple recoverable Base64 members")
    return members


def candidate_compressed_streams() -> list[tuple[str, bytes, bytes, str]]:
    candidates: list[tuple[str, bytes, bytes, str]] = []

    if SOURCE.is_file():
        encoded = normalized(SOURCE)
        try:
            compressed = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            try:
                members = split_base64_members(encoded)
            except (binascii.Error, ValueError) as exc:
                candidates.append((SOURCE.name, encoded, b"", f"decode_error={exc}"))
            else:
                compressed = b"".join(members)
                detail = "member_bytes=" + ",".join(str(len(member)) for member in members)
                candidates.append((SOURCE.name + "::joined_members", encoded, compressed, detail))
        else:
            candidates.append((SOURCE.name, encoded, compressed, "strict_single_member"))

    if all(part.is_file() for part in PARTS):
        encoded = b"".join(normalized(part) for part in PARTS)
        try:
            compressed = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            candidates.append(("+".join(part.name for part in PARTS), encoded, b"", f"decode_error={exc}"))
        else:
            candidates.append(("+".join(part.name for part in PARTS), encoded, compressed, "strict_part_join"))

    return candidates


def main() -> None:
    diagnostics: list[str] = []
    accepted: tuple[str, bytes, bytes, bytes] | None = None

    for name, encoded, compressed, transport_detail in candidate_compressed_streams():
        transport_sha = sha256(encoded)
        if not compressed:
            diagnostics.append(
                f"{name}: transport_bytes={len(encoded)} transport_sha256={transport_sha} {transport_detail}"
            )
            continue

        gzip_sha = sha256(compressed)
        try:
            raw = gzip.decompress(compressed)
        except (EOFError, OSError) as exc:
            diagnostics.append(
                f"{name}: transport_bytes={len(encoded)} transport_sha256={transport_sha} "
                f"gzip_bytes={len(compressed)} gzip_sha256={gzip_sha} {transport_detail} decompress_error={exc}"
            )
            continue

        raw_sha = sha256(raw)
        raw_match = len(raw) == EXPECTED["raw_bytes"] and raw_sha == EXPECTED["raw_sha256"]
        diagnostics.append(
            f"{name}: transport_bytes={len(encoded)} transport_sha256={transport_sha} "
            f"legacy_transport_match={transport_sha == EXPECTED['legacy_base64_sha256']} "
            f"gzip_bytes={len(compressed)} gzip_sha256={gzip_sha} "
            f"legacy_gzip_match={gzip_sha == EXPECTED['legacy_gzip_sha256']} "
            f"raw_bytes={len(raw)} raw_sha256={raw_sha} raw_match={raw_match} {transport_detail}"
        )

        # Only the exact preregistered executable Python bytes are scientific
        # authority. Wrapper or member boundaries are transport-only.
        if raw_match:
            if accepted is not None and accepted[3] != raw:
                raise SystemExit("multiple distinct transports matched the frozen raw executable identity")
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
