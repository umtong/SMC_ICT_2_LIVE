from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

import requests

URL = "https://datasets.tardis.dev/v1/bybit/derivative_ticker/2022/01/01/BTCUSDT.csv.gz"
ALLOWED_DATE_FRAGMENT = "/2022/01/01/"
FIELD_CANDIDATES = (
    "exchange",
    "symbol",
    "timestamp",
    "local_timestamp",
    "last_price",
    "index_price",
    "mark_price",
    "open_interest",
    "funding_rate",
    "predicted_funding_rate",
    "funding_timestamp",
    "next_funding_timestamp",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if ALLOWED_DATE_FRAGMENT not in URL or "/2024/" in URL or "/2025/" in URL or "/2026/" in URL:
        raise AssertionError("probe URL violates frozen date scope")
    response = requests.get(URL, timeout=120, headers={"User-Agent": "SMC-ICT-2-tardis-schema-probe/1.0"})
    response.raise_for_status()
    raw = response.content
    source_sha = hashlib.sha256(raw).hexdigest()
    reader = csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(raw)), encoding="utf-8", newline=""))
    if reader.fieldnames is None:
        raise RuntimeError("missing CSV header")
    header = list(reader.fieldnames)
    row_count = 0
    first_rows: list[dict[str, str]] = []
    non_null = {field: 0 for field in header}
    distinct_changes = {field: 0 for field in header}
    previous: dict[str, str | None] = {field: None for field in header}
    minimum_timestamp: int | None = None
    maximum_timestamp: int | None = None
    for row in reader:
        row_count += 1
        if len(first_rows) < 5:
            first_rows.append({key: row.get(key, "") for key in header})
        for field in header:
            value = row.get(field, "")
            if value not in (None, ""):
                non_null[field] += 1
            if previous[field] is not None and value != previous[field]:
                distinct_changes[field] += 1
            previous[field] = value
        for ts_field in ("local_timestamp", "timestamp"):
            value = row.get(ts_field, "")
            if value not in (None, ""):
                timestamp = int(value)
                minimum_timestamp = timestamp if minimum_timestamp is None else min(minimum_timestamp, timestamp)
                maximum_timestamp = timestamp if maximum_timestamp is None else max(maximum_timestamp, timestamp)
                break
    result = {
        "schema_version": 1,
        "status": "SOURCE_SCHEMA_PROBE_PASS",
        "url": URL,
        "source_bytes": len(raw),
        "source_sha256": source_sha,
        "header": header,
        "row_count": row_count,
        "minimum_timestamp": minimum_timestamp,
        "maximum_timestamp": maximum_timestamp,
        "field_summary": {
            field: {
                "present": field in header,
                "non_null": non_null.get(field, 0),
                "distinct_changes": distinct_changes.get(field, 0),
            }
            for field in FIELD_CANDIDATES
        },
        "first_rows": first_rows,
        "strategy_outcomes_read": false,
        "candidate_pnl_computed": false,
        "orders_submitted": false,
        "2024_opened": false,
        "2025_or_2026_opened": false,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "PROBE.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "HEADER.txt").write_text(",".join(header) + "\n", encoding="utf-8")
    sums = []
    for path in sorted(args.output.iterdir()):
        if path.name == "SHA256SUMS.txt" or not path.is_file():
            continue
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (args.output / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "source_bytes", "source_sha256", "header", "row_count")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
