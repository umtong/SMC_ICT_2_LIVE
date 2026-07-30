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


def unique_text_candidates(base: str, parts: list[str]) -> Iterable[tuple[str, str]]:
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


def inspect_gzip(name: str, gz: bytes, manifest: dict[str, object]) -> tuple[dict[str, object], bytes | None]:
    attempt: dict[str, object] = {
        "candidate": name,
        "gzip_bytes": len(gz),
        "gzip_sha256": hashlib.sha256(gz).hexdigest(),
    }
    attempt["gzip_hash_matches"] = attempt["gzip_sha256"] == manifest["gzip_sha256"]

    raw: bytes | None = None
    try:
        raw = gzip.decompress(gz)
        attempt["full_decompress_error"] = None
        attempt["source_bytes"] = len(raw)
        attempt["source_sha256"] = hashlib.sha256(raw).hexdigest()
    except Exception as exc:
        attempt["full_decompress_error"] = f"{type(exc).__name__}: {exc}"
        partial, partial_error = partial_gzip_decompress(gz)
        attempt["partial_decompress_error"] = partial_error
        attempt["partial_source_bytes"] = len(partial)
        attempt["partial_source_sha256"] = hashlib.sha256(partial).hexdigest()
        raw = partial if partial else None

    if raw is not None and is_exact_source(raw, manifest):
        attempt["status"] = "selected_exact_source_match"
    else:
        attempt["status"] = "source_not_exact"
    return attempt, raw


def splice_candidates(named_gz: list[tuple[str, bytes]], expected_len: int) -> Iterable[tuple[str, bytes]]:
    """Recover a stream when one carrier holds a valid prefix and another a valid suffix.

    The search is hash-authoritative and bounded: at most O(n * expected_len)
    candidates for the two small carriers in this claim.
    """
    seen_hashes: set[str] = set()
    for left_name, left in named_gz:
        for right_name, right in named_gz:
            if left_name == right_name:
                continue
            min_prefix = max(1, expected_len - len(right))
            max_prefix = min(len(left), expected_len - 1)
            for prefix_len in range(min_prefix, max_prefix + 1):
                suffix_len = expected_len - prefix_len
                if suffix_len <= 0 or suffix_len > len(right):
                    continue
                candidate = left[:prefix_len] + right[-suffix_len:]
                digest = hashlib.sha256(candidate).hexdigest()
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                yield f"splice_{left_name}_prefix{prefix_len}_{right_name}_suffix{suffix_len}", candidate


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    base = compact_text(BASE_PATH) if BASE_PATH.exists() else ""
    part_paths = sorted(ROOT.glob(PART_GLOB))
    parts = [compact_text(path) for path in part_paths]

    attempts: list[dict[str, object]] = []
    selected: dict[str, object] | None = None
    selected_raw: bytes | None = None
    largest_partial = b""
    largest_partial_name: str | None = None
    named_gz: list[tuple[str, bytes]] = []

    for name, text in unique_text_candidates(base, parts):
        try:
            gz = decode_candidate(text)
        except Exception as exc:
            attempts.append({
                "candidate": name,
                "base64_chars": len(text),
                "status": "base64_decode_error",
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        named_gz.append((name, gz))
        attempt, raw = inspect_gzip(name, gz, manifest)
        attempt["base64_chars"] = len(text)
        attempts.append(attempt)
        if raw is not None and len(raw) > len(largest_partial):
            largest_partial = raw
            largest_partial_name = name
        if attempt["status"] == "selected_exact_source_match":
            selected = attempt
            selected_raw = raw
            break

    splice_attempts = 0
    if selected is None and len(named_gz) >= 2:
        expected_gzip_bytes = int(manifest["gzip_bytes"])
        for name, gz in splice_candidates(named_gz, expected_gzip_bytes):
            splice_attempts += 1
            attempt, raw = inspect_gzip(name, gz, manifest)
            if attempt["gzip_hash_matches"] or attempt["status"] == "selected_exact_source_match":
                attempts.append(attempt)
            if raw is not None and len(raw) > len(largest_partial):
                largest_partial = raw
                largest_partial_name = name
            if attempt["status"] == "selected_exact_source_match":
                selected = attempt
                selected_raw = raw
                attempts.append(attempt)
                break

    if selected_raw is not None:
        OUTPUT_PATH.write_bytes(selected_raw)

    partial_summary: dict[str, object] | None = None
    if largest_partial:
        PARTIAL_PATH.write_bytes(largest_partial)
        tail = largest_partial.decode("utf-8", errors="replace")[-4000:]
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
        "splice_attempts": splice_attempts,
        "attempts": attempts,
        "largest_partial": partial_summary,
        "selected": selected,
    }
    report_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")

    if selected is None:
        print(report_text)
        raise RuntimeError(
            "No carrier or prefix/suffix splice produced the exact manifest source."
        )

    print(json.dumps(selected, sort_keys=True))


if __name__ == "__main__":
    main()
