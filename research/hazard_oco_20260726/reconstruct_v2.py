from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_encoded(root: Path, record: dict) -> str:
    if "encoded_parts" in record:
        encoded = "".join(
            (root / name).read_text(encoding="utf-8").strip()
            for name in record["encoded_parts"]
        )
    else:
        encoded = (root / record["encoded_path"]).read_text(encoding="utf-8").strip()
    expected = record.get("base64_characters")
    if expected is not None and len(encoded) != int(expected):
        raise AssertionError(
            f"base64 character count mismatch for {record['output_path']}: "
            f"observed={len(encoded)} expected={expected}"
        )
    return encoded


def apply_json_serialization_correction(raw: bytes) -> bytes:
    text = raw.decode("utf-8")
    replacements = (
        (
            'def canonical_sha256(obj: object) -> str:\n'
            '    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()\n',
            'def json_default(obj: object) -> object:\n'
            '    """Convert deterministic NumPy/path scalars for evidence serialization only."""\n'
            '    if isinstance(obj, np.generic):\n'
            '        return obj.item()\n'
            '    if isinstance(obj, np.ndarray):\n'
            '        return obj.tolist()\n'
            '    if isinstance(obj, Path):\n'
            '        return str(obj)\n'
            '    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")\n\n\n'
            'def canonical_sha256(obj: object) -> str:\n'
            '    return hashlib.sha256(\n'
            '        json.dumps(obj, sort_keys=True, separators=(",", ":"), default=json_default).encode()\n'
            '    ).hexdigest()\n',
        ),
        (
            'def write_json(path: Path, obj: object) -> None:\n'
            '    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\\n", encoding="utf-8")\n',
            'def write_json(path: Path, obj: object) -> None:\n'
            '    path.write_text(\n'
            '        json.dumps(obj, indent=2, sort_keys=True, allow_nan=False, default=json_default) + "\\n",\n'
            '        encoding="utf-8",\n'
            '    )\n',
        ),
        (
            '    print("DECISION_READY_RESULT=" + json.dumps(result, sort_keys=True, separators=(",", ":")))\n',
            '    print(\n'
            '        "DECISION_READY_RESULT="\n'
            '        + json.dumps(result, sort_keys=True, separators=(",", ":"), default=json_default)\n'
            '    )\n',
        ),
    )
    for old, new in replacements:
        count = text.count(old)
        if count != 1:
            raise AssertionError(f"serialization correction anchor count={count}")
        text = text.replace(old, new)
    return text.encode("utf-8")


def main() -> int:
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "v2_bundle_manifest.json").read_text(encoding="utf-8"))
    correction = json.loads(
        (root / "CORRECTION_005_JSON_SERIALIZATION_AFTER_RESULT.json").read_text(encoding="utf-8")
    )
    for record in manifest["files"]:
        encoded = read_encoded(root, record)
        compressed = base64.b64decode(encoded, validate=True)
        if sha256(compressed) != record["gzip_sha256"]:
            raise AssertionError(f"gzip SHA mismatch: {record['output_path']}")
        raw = gzip.decompress(compressed)
        if len(raw) != record["output_bytes"]:
            raise AssertionError(f"byte count mismatch: {record['output_path']}")
        if sha256(raw) != record["output_sha256"]:
            raise AssertionError(f"source SHA mismatch: {record['output_path']}")
        original_sha = sha256(raw)
        if record["output_path"] == "run_v2.py":
            raw = apply_json_serialization_correction(raw)
            if sha256(raw) != correction["corrected_output_sha256"]:
                raise AssertionError("corrected run_v2.py SHA mismatch")
            if len(raw) != int(correction["corrected_output_bytes"]):
                raise AssertionError("corrected run_v2.py byte count mismatch")
        path = root / record["output_path"]
        path.write_bytes(raw)
        print(
            f"RECONSTRUCTED {path.name} base64={len(encoded)} original={original_sha} "
            f"final={sha256(raw)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
