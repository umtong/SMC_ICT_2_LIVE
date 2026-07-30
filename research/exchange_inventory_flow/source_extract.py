from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.request
from datetime import date
from pathlib import Path

SOURCES = {
    "BTCUSDT": {
        "url": "https://raw.githubusercontent.com/coinmetrics/data/master/csv/btc.csv",
        "git_blob_sha1": "5e50f336d268e1f3a38e9885b5aaef36de529700",
    },
    "ETHUSDT": {
        "url": "https://raw.githubusercontent.com/coinmetrics/data/master/csv/eth.csv",
        "git_blob_sha1": "d8e4f389b37626f432a923805e5cc5fa2ad5490b",
    },
}
START = date.fromisoformat("2020-01-01")
END = date.fromisoformat("2023-12-31")
COLUMNS = (
    "time", "FlowInExNtv", "FlowOutExNtv", "SplyExNtv", "SplyCur",
    "AssetCompletionTime", "AssetEODCompletionTime",
)


def git_blob_sha1(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def fetch(url: str, expected_blob: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SMC_ICT_2_LIVE-exchange-inventory/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = response.read()
    observed = git_blob_sha1(payload)
    if observed != expected_blob:
        raise RuntimeError(f"source blob changed: {observed} != {expected_blob}")
    return payload


def extract(symbol: str, payload: bytes, output: Path) -> dict[str, object]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise RuntimeError(f"{symbol} source columns missing: {missing}")
    rows = []
    for row in reader:
        d = date.fromisoformat(row["time"])
        if START <= d <= END:
            rows.append({column: row.get(column, "") for column in COLUMNS})
    expected = (END - START).days + 1
    if len(rows) != expected:
        raise RuntimeError(f"{symbol}: expected {expected} rows, found {len(rows)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    raw = output.read_bytes()
    return {
        "symbol": symbol,
        "source_url": SOURCES[symbol]["url"],
        "git_blob_sha1": git_blob_sha1(payload),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "source_bytes": len(payload),
        "filtered_rows": len(rows),
        "filtered_sha256": hashlib.sha256(raw).hexdigest(),
        "filtered_bytes": len(raw),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for symbol, source in SOURCES.items():
        payload = fetch(source["url"], source["git_blob_sha1"])
        records.append(extract(symbol, payload, args.output_dir / f"{symbol}_2020_2023.csv"))
    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260730-EXCHANGE-INVENTORY-FLOW-CORE-001",
        "start": START.isoformat(),
        "end": END.isoformat(),
        "availability_rule": "source day d actionable no earlier than d+2 00:00 UTC",
        "records": records,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    (args.output_dir / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
