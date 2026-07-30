from __future__ import annotations

import base64
import gzip
import hashlib
import json
import zlib
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "SOURCE_MANIFEST.json"
BASE_PATH = ROOT / "run.py.gz.b64"
PART_GLOB = "run.py.gz.b64.part*"
OUTPUT_PATH = ROOT / "run.py"
PARTIAL_PATH = ROOT / "run.partial.py"
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


def partial_gzip_decompress(data: bytes) -> tuple[bytes, str | None]:
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = b""
    error: str | None = None
    try:
        raw += decoder.decompress(data)
        raw += decoder.flush()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        try:
            raw += decoder.flush()
        except Exception:
            pass
    return raw, error


def is_exact_source(raw: bytes, manifest: dict[str, object]) -> bool:
    return (
        len(raw) == int(manifest["source_bytes"])
        and hashlib.sha256(raw).hexdigest() == manifest["source_sha256"]
    )


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    base = compact_text(BASE_PATH) if BASE_PATH.exists() else ""
    part_paths = sorted(ROOT.glob(PART_GLOB))
    parts = [compact_text(path) for path in part_paths]

    attempts: list[dict[str, object]] = []
    selected: dict[str, object] | None = None
    largest_partial = b""
    largest_partial_name: str | None = None

    for name, candidate in unique_candidates(base, parts):
        attempt: dict[str, object] = {
            "candidate": name,
            "base64_chars": len(candidate),
        }
        try:
            gz = decode_candidate(candidate)
            attempt["gzip_bytes"] = len(gz)
            attempt["gzip_sha256"] = hashlib.sha256(gz).hexdigest()
            attempt["gzip_hash_matches"] = attempt["gzip_sha256"] == manifest["gzip_sha256"]

            raw: bytes | None = None
            full_error: str | None = None
            try:
                raw = gzip.decompress(gz)
            except Exception as exc:
                full_error = f"{type(exc).__name__}: {exc}"

            if raw is not None:
                attempt["source_bytes"] = len(raw)
                attempt["source_sha256"] = hashlib.sha256(raw).hexdigest()
                attempt["full_decompress_error"] = None
                if len(raw) > len(largest_partial):
                    largest_partial = raw
                    largest_partial_name = name
                if is_exact_source(raw, manifest):
                    OUTPUT_PATH.write_bytes(raw)
                    attempt["status"] = "selected_exact_source_match"
                    attempts.append(attempt)
                    selected = attempt
                    break
            else:
                partial, partial_error = partial_gzip_decompress(gz)
                attempt["full_decompress_error"] = full_error
                attempt["partial_decompress_error"] = partial_error
                attempt["partial_source_bytes"] = len(partial)
                attempt["partial_source_sha256"] = hashlib.sha256(partial).hexdigest()
                if len(partial) > len(largest_partial):
                    largest_partial = partial
                    largest_partial_name = name
                if is_exact_source(partial, manifest):
                    OUTPUT_PATH.write_bytes(partial)
                    attempt["status"] = "selected_exact_source_match_from_truncated_gzip"
                    attempts.append(attempt)
                    selected = attempt
                    break

            attempt["status"] = (
                "gzip_hash_mismatch_or_incomplete_source"
                if not attempt["gzip_hash_matches"]
                else "gzip_hash_match_but_source_mismatch"
            )
            attempts.append(attempt)
        except Exception as exc:
            attempt["status"] = "base64_decode_error"
            attempt["error"] = f"{type(exc).__name__}: {exc}"
            attempts.append(attempt)

    partial_summary: dict[str, object] | None = None
    if largest_partial:
        PARTIAL_PATH.write_bytes(largest_partial)
        try:
            tail = largest_partial.decode("utf-8", errors="replace")[-4000:]
        except Exception:
            tail = ""
        partial_summary = {
            "candidate": largest_partial_name,
            "bytes": len(largest_partial),
            "sha256": hashlib.sha256(largest_partial).hexdigest(),
            "utf8_tail": tail,
        }

    report = {
        "manifest": manifest,
        "primary_exists": BASE_PATH.exists(),
        "primary_base64_chars": len(base),
        "part_files": [path.name for path in part_paths],
        "part_base64_chars": [len(part) for part in parts],
        "attempts": attempts,
        "largest_partial": partial_summary,
        "selected": selected,
    }
    report_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")

    if selected is None:
        print(report_text)
        raise RuntimeError(
            "No carrier produced the exact manifest source. The largest recoverable "
            "partial source and its tail were recorded."
        )

    print(json.dumps(selected, sort_keys=True))


if __name__ == "__main__":
    main()
