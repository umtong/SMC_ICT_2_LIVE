from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.request
from datetime import date
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/eth.csv"
EXPECTED_GIT_BLOB_SHA1 = "d8e4f389b37626f432a923805e5cc5fa2ad5490b"
START = date.fromisoformat("2020-01-01")
END = date.fromisoformat("2023-12-31")
COLUMNS = (
    "time",
    "FeeTotNtv",
    "IssTotNtv",
    "TxCnt",
    "TxTfrCnt",
    "AdrActCnt",
    "FlowInExNtv",
    "FlowOutExNtv",
    "ReferenceRateUSD",
    "AssetCompletionTime",
    "AssetEODCompletionTime",
)


def git_blob_sha1(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def download() -> bytes:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "SMC_ICT_2_LIVE-eth-blockspace-demand/1.0"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = response.read()
    if not payload.startswith(b"time,"):
        raise RuntimeError("unexpected Coin Metrics CSV header")
    observed_blob = git_blob_sha1(payload)
    if observed_blob != EXPECTED_GIT_BLOB_SHA1:
        raise RuntimeError(
            f"Coin Metrics git blob changed: {observed_blob} != {EXPECTED_GIT_BLOB_SHA1}"
        )
    return payload


def extract(payload: bytes, output: Path) -> dict[str, object]:
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise RuntimeError(f"source columns missing: {missing}")

    rows: list[dict[str, str]] = []
    for row in reader:
        row_date = date.fromisoformat(row["time"])
        if START <= row_date <= END:
            rows.append({column: row.get(column, "") for column in COLUMNS})

    expected_days = (END - START).days + 1
    if len(rows) != expected_days:
        raise RuntimeError(f"expected {expected_days} daily rows, found {len(rows)}")
    if rows[0]["time"] != START.isoformat() or rows[-1]["time"] != END.isoformat():
        raise RuntimeError("source date boundary mismatch")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    output_bytes = output.read_bytes()
    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260730-ETH-BLOCKSPACE-DEMAND-CORE-001",
        "source_url": SOURCE_URL,
        "expected_git_blob_sha1": EXPECTED_GIT_BLOB_SHA1,
        "observed_git_blob_sha1": git_blob_sha1(payload),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "source_bytes": len(payload),
        "filtered_start": START.isoformat(),
        "filtered_end": END.isoformat(),
        "filtered_rows": len(rows),
        "filtered_columns": list(COLUMNS),
        "filtered_sha256": hashlib.sha256(output_bytes).hexdigest(),
        "filtered_bytes": len(output_bytes),
        "availability_rule": "source day d becomes actionable no earlier than d+2 00:00 UTC",
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    return manifest


def self_test() -> None:
    sample = b"hello\n"
    assert git_blob_sha1(sample) == hashlib.sha1(b"blob 6\0hello\n").hexdigest()
    print("ETH_BLOCKSPACE_SOURCE_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None or args.manifest is None:
        raise SystemExit("--output and --manifest are required")
    payload = download()
    manifest = extract(payload, args.output)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
