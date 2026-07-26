from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent
AMENDMENT_PATH = ROOT / "amendment_006_canonical_reproduction.json"
SCIENTIFIC_FILES = (
    "development_2022_opportunities.csv",
    "development_result.json",
    "result_summary.json",
    "source_manifest.json",
    "training_2021_opportunities.csv",
    "training_model.json",
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalized_float(value: float) -> float | str:
    number = float(value)
    if math.isnan(number):
        return "NaN"
    if math.isinf(number):
        return "Infinity" if number > 0 else "-Infinity"
    return float(format(number, ".12g"))


def canonical_json_value(value: Any, remove_cache_hit: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            key: canonical_json_value(item, remove_cache_hit)
            for key, item in sorted(value.items())
            if not (remove_cache_hit and key == "cache_hit")
        }
    if isinstance(value, list):
        return [canonical_json_value(item, remove_cache_hit) for item in value]
    if isinstance(value, float):
        return normalized_float(value)
    return value


def canonical_json_bytes(path: Path, remove_cache_hit: bool = False) -> bytes:
    value = json.loads(path.read_text(encoding="utf-8"))
    canonical = canonical_json_value(value, remove_cache_hit)
    return json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_csv_bytes(path: Path) -> bytes:
    frame = pd.read_csv(path)
    rows: list[list[Any]] = []
    numeric = {
        column: pd.api.types.is_numeric_dtype(frame[column])
        for column in frame.columns
    }
    for _, row in frame.iterrows():
        values: list[Any] = []
        for column in frame.columns:
            value = row[column]
            if pd.isna(value):
                values.append(None)
            elif numeric[column]:
                values.append(normalized_float(float(value)))
            else:
                values.append(str(value))
        rows.append(values)
    canonical = {"columns": list(frame.columns), "rows": rows}
    return json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def fingerprint_file(path: Path) -> str:
    if path.suffix.lower() == ".csv":
        payload = canonical_csv_bytes(path)
    else:
        payload = canonical_json_bytes(
            path,
            remove_cache_hit=path.name == "source_manifest.json",
        )
    return sha256_bytes(payload)


def fingerprint_directory(directory: Path) -> dict[str, str]:
    return {
        name: fingerprint_file(directory / name)
        for name in SCIENTIFIC_FILES
    }


def verify(directory: Path) -> dict[str, Any]:
    amendment = json.loads(AMENDMENT_PATH.read_text(encoding="utf-8"))
    expected = amendment["canonical_contract"]["canonical_sha256"]
    actual = fingerprint_directory(directory)
    if actual != expected:
        raise AssertionError({"expected": expected, "actual": actual})
    raw_summary = sha256_bytes((directory / "result_summary.json").read_bytes())
    expected_raw = amendment["canonical_contract"]["raw_result_summary_required"]
    if raw_summary != expected_raw:
        raise AssertionError({
            "expected_raw_result_summary": expected_raw,
            "actual_raw_result_summary": raw_summary,
        })
    result = {
        "canonical_fingerprints": actual,
        "raw_result_summary_sha256": raw_summary,
        "scientific_reproduction_pass": True,
    }
    print("CME_GAP_CANONICAL_REPRODUCTION=" + json.dumps(result, sort_keys=True))
    return result


def self_test() -> None:
    left = {
        "metric": 0.1234567890123456,
        "records": [{"cache_hit": False, "value": 1.0000000000000002}],
    }
    right = {
        "metric": 0.1234567890123457,
        "records": [{"cache_hit": True, "value": 1.0}],
    }
    left_payload = json.dumps(
        canonical_json_value(left, remove_cache_hit=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    right_payload = json.dumps(
        canonical_json_value(right, remove_cache_hit=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert left_payload == right_payload

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        first = pd.DataFrame({
            "timestamp": ["2021-01-01 00:00:00+00:00"],
            "probability": [0.1511334628326619],
        })
        second = pd.DataFrame({
            "timestamp": ["2021-01-01 00:00:00+00:00"],
            "probability": [0.15113346283266188],
        })
        first.to_csv(root / "first.csv", index=False)
        second.to_csv(root / "second.csv", index=False)
        assert canonical_csv_bytes(root / "first.csv") == canonical_csv_bytes(root / "second.csv")
    print("CANONICAL_FINGERPRINT_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        verify(args.directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
