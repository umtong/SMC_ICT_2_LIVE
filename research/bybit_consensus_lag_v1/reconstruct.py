from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
SOURCE_PARTS = (
    ROOT / "run.py.gz.b64",
    ROOT / "run.py.gz.b64.part01",
)
TARGET = ROOT / "run.py"
EXPECTED = {
    "base64_bytes": 14444,
    "base64_sha256": "7a288e93a58e8fba41de928208c966a61132c72206d152b714e9ec5b0ebdde7b",
    "gzip_bytes": 10832,
    "gzip_sha256": "99ca27b53a771d00d89a2a289e9c10ec96a75c5ca714ab3195856e4f71a4ad46",
    "raw_bytes": 39343,
    "raw_sha256": "366aa871dcff28a49e64782560737d0a7bc54c0ad97effe40b72d24f1b0f4bf8",
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def decode_stream(encoded: bytes) -> tuple[bytes, bytes]:
    compressed = base64.b64decode(encoded, validate=True)
    raw = gzip.decompress(compressed)
    return compressed, raw


def longest_suffix_prefix(left: bytes, right: bytes) -> int:
    for size in range(min(len(left), len(right)), 0, -1):
        if left[-size:] == right[:size]:
            return size
    return 0


def candidate_streams(parts: list[bytes]) -> Iterable[tuple[str, bytes]]:
    # Each checked-in file may be either the complete immutable transport, a
    # literal base64 fragment, or a separately compressed source fragment.
    for index, part in enumerate(parts):
        yield f"single:{SOURCE_PARTS[index].name}", part

    if len(parts) == 2:
        left, right = parts
        yield "literal:left+right", left + right
        yield "literal:right+left", right + left
        overlap_lr = longest_suffix_prefix(left, right)
        overlap_rl = longest_suffix_prefix(right, left)
        if overlap_lr:
            yield f"overlap:left+right:{overlap_lr}", left + right[overlap_lr:]
        if overlap_rl:
            yield f"overlap:right+left:{overlap_rl}", right + left[overlap_rl:]


def main() -> int:
    missing = [str(path) for path in SOURCE_PARTS if not path.is_file()]
    if missing:
        raise SystemExit(f"missing source transport part(s): {missing}")

    parts = [path.read_bytes().strip() for path in SOURCE_PARTS]
    diagnostics: dict[str, object] = {
        "expected": EXPECTED,
        "parts": [],
        "attempts": [],
    }

    decoded_parts: list[tuple[bytes, bytes] | None] = []
    for path, encoded in zip(SOURCE_PARTS, parts, strict=True):
        item: dict[str, object] = {
            "name": path.name,
            "base64_bytes": len(encoded),
            "base64_sha256": sha256(encoded),
        }
        try:
            compressed, raw = decode_stream(encoded)
            item.update(
                {
                    "decode_status": "PASS",
                    "gzip_bytes": len(compressed),
                    "gzip_sha256": sha256(compressed),
                    "raw_bytes": len(raw),
                    "raw_sha256": sha256(raw),
                }
            )
            decoded_parts.append((compressed, raw))
        except Exception as exc:  # diagnostic only; exact raw hash remains gate
            item.update({"decode_status": "FAIL", "error": repr(exc)})
            decoded_parts.append(None)
        diagnostics["parts"].append(item)

    # First accept any transport representation that reconstructs the exact
    # preregistered raw implementation. Transport compression/layout is not an
    # economic degree of freedom; the raw code hash is the scientific identity.
    for label, encoded in candidate_streams(parts):
        attempt: dict[str, object] = {
            "label": label,
            "base64_bytes": len(encoded),
            "base64_sha256": sha256(encoded),
        }
        try:
            compressed, raw = decode_stream(encoded)
            attempt.update(
                {
                    "decode_status": "PASS",
                    "gzip_bytes": len(compressed),
                    "gzip_sha256": sha256(compressed),
                    "raw_bytes": len(raw),
                    "raw_sha256": sha256(raw),
                }
            )
        except Exception as exc:
            attempt.update({"decode_status": "FAIL", "error": repr(exc)})
            diagnostics["attempts"].append(attempt)
            continue
        diagnostics["attempts"].append(attempt)
        if len(raw) == EXPECTED["raw_bytes"] and sha256(raw) == EXPECTED["raw_sha256"]:
            TARGET.write_bytes(raw)
            diagnostics.update(
                {
                    "status": "PASS",
                    "selected_transport": label,
                    "target": str(TARGET),
                }
            )
            print(json.dumps(diagnostics, sort_keys=True))
            return 0

    # A split writer may have independently compressed source fragments. Test
    # both raw concatenation orders, again accepting only the exact raw hash.
    if len(decoded_parts) == 2 and all(item is not None for item in decoded_parts):
        raw_left = decoded_parts[0][1]  # type: ignore[index]
        raw_right = decoded_parts[1][1]  # type: ignore[index]
        for label, raw in (
            ("raw-fragments:left+right", raw_left + raw_right),
            ("raw-fragments:right+left", raw_right + raw_left),
        ):
            attempt = {
                "label": label,
                "decode_status": "PASS",
                "raw_bytes": len(raw),
                "raw_sha256": sha256(raw),
            }
            diagnostics["attempts"].append(attempt)
            if len(raw) == EXPECTED["raw_bytes"] and sha256(raw) == EXPECTED["raw_sha256"]:
                TARGET.write_bytes(raw)
                diagnostics.update(
                    {
                        "status": "PASS",
                        "selected_transport": label,
                        "target": str(TARGET),
                    }
                )
                print(json.dumps(diagnostics, sort_keys=True))
                return 0

    diagnostics["status"] = "FAIL"
    print(json.dumps(diagnostics, sort_keys=True))
    raise SystemExit("no transport representation reconstructs preregistered raw implementation")


if __name__ == "__main__":
    raise SystemExit(main())
