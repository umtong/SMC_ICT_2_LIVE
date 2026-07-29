from __future__ import annotations

import argparse
import ast
import base64
import gzip
import hashlib
import json
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Any

SOURCE_PATH = "research/bybit_premium_dislocation_20260726/run_screen.py.gz.b64"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalized_b64(payload: bytes) -> bytes:
    return b"".join(payload.split())


def decode_transport(payload: bytes) -> bytes:
    return base64.b64decode(normalized_b64(payload), validate=True)


def gzip_payload_offset(data: bytes) -> int:
    if len(data) < 18 or data[:2] != b"\x1f\x8b" or data[2] != 8:
        raise RuntimeError("not a supported gzip/deflate stream")
    flags = data[3]
    if flags & 0xE0:
        raise RuntimeError(f"reserved gzip flags set: {flags:#x}")
    cursor = 10
    if flags & 0x04:
        if cursor + 2 > len(data) - 8:
            raise RuntimeError("truncated gzip extra length")
        xlen = struct.unpack_from("<H", data, cursor)[0]
        cursor += 2 + xlen
    for bit in (0x08, 0x10):
        if flags & bit:
            end = data.find(b"\x00", cursor, len(data) - 8)
            if end < 0:
                raise RuntimeError("unterminated gzip text field")
            cursor = end + 1
    if flags & 0x02:
        cursor += 2
    if cursor >= len(data) - 8:
        raise RuntimeError("empty or truncated deflate payload")
    return cursor


def salvage_crc_only(compressed: bytes) -> tuple[bytes, dict[str, Any]]:
    start = gzip_payload_offset(compressed)
    expected_crc, expected_size = struct.unpack("<II", compressed[-8:])
    obj = zlib.decompressobj(-zlib.MAX_WBITS)
    raw = obj.decompress(compressed[start:-8]) + obj.flush()
    if not obj.eof or obj.unused_data:
        raise RuntimeError("raw deflate did not terminate exactly")
    observed_crc = zlib.crc32(raw) & 0xFFFFFFFF
    observed_size = len(raw) & 0xFFFFFFFF
    if observed_size != expected_size:
        raise RuntimeError(
            f"gzip ISIZE mismatch: observed={observed_size} expected={expected_size}"
        )
    if observed_crc == expected_crc:
        raise RuntimeError("standard gzip unexpectedly had a valid CRC")
    return raw, {
        "mode": "CRC_TRAILER_ONLY_RECOVERY",
        "gzip_payload_offset": start,
        "expected_crc32": f"{expected_crc:08x}",
        "observed_crc32": f"{observed_crc:08x}",
        "expected_isize": expected_size,
        "observed_isize": observed_size,
    }


def validate_source(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8")
    tree = ast.parse(text, filename="run_screen.py")
    compile(tree, "run_screen.py", "exec")
    if "BYBIT_NATIVE_PREMIUM_DISLOCATION_FATAL_V1" not in text:
        raise RuntimeError("reconstructed source lacks frozen study identifier")
    if "2024_opened" not in text or "orders_submitted" not in text:
        raise RuntimeError("reconstructed source lacks sealed-boundary assertions")
    return {
        "raw_sha256": sha256(raw),
        "raw_bytes": len(raw),
        "line_count": text.count("\n") + 1,
    }


def git_revisions(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%H", "--all", "--", SOURCE_PATH],
        check=True,
        capture_output=True,
        text=True,
    )
    revisions = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return revisions


def git_blob(repo: Path, revision: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{revision}:{SOURCE_PATH}"],
        check=True,
        capture_output=True,
    )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    args = parser.parse_args()

    candidates: list[dict[str, Any]] = []
    chosen_raw: bytes | None = None
    chosen_meta: dict[str, Any] | None = None

    for revision in git_revisions(args.repo):
        try:
            transport = git_blob(args.repo, revision)
            compressed = decode_transport(transport)
            raw = gzip.decompress(compressed)
            source_meta = validate_source(raw)
            chosen_raw = raw
            chosen_meta = {
                "mode": "VALID_HISTORICAL_GZIP",
                "source_revision": revision,
                "transport_sha256": sha256(normalized_b64(transport)),
                "gzip_sha256": sha256(compressed),
                **source_meta,
            }
            candidates.append({"revision": revision, "status": "VALID", **source_meta})
            break
        except Exception as exc:
            candidates.append({"revision": revision, "status": "REJECTED", "error": repr(exc)})

    if chosen_raw is None:
        transport = args.current.read_bytes()
        compressed = decode_transport(transport)
        raw, recovery = salvage_crc_only(compressed)
        source_meta = validate_source(raw)
        chosen_raw = raw
        chosen_meta = {
            **recovery,
            "source_revision": "CURRENT_BRANCH_GIT_BLOB",
            "transport_sha256": sha256(normalized_b64(transport)),
            "gzip_sha256": sha256(compressed),
            **source_meta,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(chosen_raw)
    payload = {
        "schema_version": 1,
        "repair_id": "REPAIR-20260730-BYBIT-PREMIUM-SOURCE-CRC-001",
        "scientific_contract_changed": False,
        "chosen": chosen_meta,
        "historical_candidates": candidates,
    }
    args.diagnostics.parent.mkdir(parents=True, exist_ok=True)
    args.diagnostics.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(chosen_meta, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
