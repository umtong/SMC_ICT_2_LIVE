from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "SOURCE_MANIFEST.json"
BASE_PATH = ROOT / "run.py.gz.b64"
PART_GLOB = "run.py.gz.b64.part*"
OUTPUT_PATH = ROOT / "run.py"
REPORT_PATH = ROOT / "MATERIALIZATION_REPORT.json"


def compact_text(path: Path) -> str:
    return "".join(path.read_text(encoding="utf-8").split())


def unique_candidates(base: str, parts: list[str]) -> Iterable[tuple[str, str]]:
    seen: set[str] = set()

    def emit(name: str, value: str) -> Iterable[tuple[str, str]]:
        if value and value not in seen:
            seen.add(value)
            yield name, value

    yield from emit("primary", base)
    for index, part in enumerate(parts):
        yield from emit(f"part_{index:02d}", part)
    if parts:
        joined = "".join(parts)
        yield from emit("parts_concat", joined)
        yield from emit("primary_then_parts", base + joined)
        yield from emit("parts_then_primary", joined + base)


def decode_candidate(text: str) -> bytes:
    padded = text + ("=" * ((-len(text)) % 4))
    return base64.b64decode(padded, validate=False)


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    base = compact_text(BASE_PATH) if BASE_PATH.exists() else ""
    part_paths = sorted(ROOT.glob(PART_GLOB))
    parts = [compact_text(path) for path in part_paths]

    attempts: list[dict[str, object]] = []
    selected: dict[str, object] | None = None

    for name, candidate in unique_candidates(base, parts):
        attempt: dict[str, object] = {
            "candidate": name,
            "base64_chars": len(candidate),
        }
        try:
            gz = decode_candidate(candidate)
            attempt["gzip_bytes"] = len(gz)
            attempt["gzip_sha256"] = hashlib.sha256(gz).hexdigest()
            if attempt["gzip_sha256"] != manifest["gzip_sha256"]:
                attempt["status"] = "gzip_hash_mismatch"
                attempts.append(attempt)
                continue

            raw = gzip.decompress(gz)
            attempt["source_bytes"] = len(raw)
            attempt["source_sha256"] = hashlib.sha256(raw).hexdigest()
            if len(raw) != manifest["source_bytes"]:
                attempt["status"] = "source_length_mismatch"
                attempts.append(attempt)
                continue
            if attempt["source_sha256"] != manifest["source_sha256"]:
                attempt["status"] = "source_hash_mismatch"
                attempts.append(attempt)
                continue

            OUTPUT_PATH.write_bytes(raw)
            attempt["status"] = "selected_exact_manifest_match"
            attempts.append(attempt)
            selected = attempt
            break
        except Exception as exc:
            attempt["status"] = "decode_or_decompress_error"
            attempt["error"] = f"{type(exc).__name__}: {exc}"
            attempts.append(attempt)

    report = {
        "manifest": manifest,
        "primary_exists": BASE_PATH.exists(),
        "primary_base64_chars": len(base),
        "part_files": [path.name for path in part_paths],
        "part_base64_chars": [len(part) for part in parts],
        "attempts": attempts,
        "selected": selected,
    }
    report_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")

    if selected is None:
        print(report_text)
        raise RuntimeError(
            "No declared carrier or deterministic carrier combination matched "
            "the manifest gzip and source hashes."
        )

    print(json.dumps(selected, sort_keys=True))


if __name__ == "__main__":
    main()
