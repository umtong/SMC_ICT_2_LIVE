from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

EXCHANGE = "binance-futures"
SYMBOL = "BTCUSDT"
DATE = "2025-08-01"
DATA_TYPES = ("book_ticker", "trades", "book_snapshot_5")
MAX_BYTES = 8 * 1024**3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def dataset_url(data_type: str) -> str:
    year, month, day = DATE.split("-")
    return (
        f"https://datasets.tardis.dev/v1/{EXCHANGE}/{data_type}/"
        f"{year}/{month}/{day}/{SYMBOL}.csv.gz"
    )


def download(url: str, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    started = time.time()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SMC-ICT-2-LIVE-research/1.0"},
    )
    with urllib.request.urlopen(request, timeout=300) as response, temporary.open("wb") as output:
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_BYTES:
            raise RuntimeError(f"declared file too large: {declared} bytes for {url}")
        copied = 0
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            copied += len(block)
            if copied > MAX_BYTES:
                raise RuntimeError(f"download exceeded {MAX_BYTES} bytes for {url}")
            output.write(block)
    temporary.replace(path)
    return {
        "url": url,
        "compressed_bytes": path.stat().st_size,
        "download_seconds": time.time() - started,
        "content_length_header": int(declared) if declared and declared.isdigit() else None,
        "sha256": sha256_file(path),
    }


def inspect_gzip(path: Path, sample_path: Path) -> dict[str, Any]:
    row_count = 0
    header: list[str] | None = None
    sample_lines: list[str] = []
    first_local_timestamp = None
    last_local_timestamp = None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if row_count == 0:
                header = row
                if "local_timestamp" not in header or "timestamp" not in header:
                    raise RuntimeError(f"required clocks missing from {path}: {header}")
                local_index = header.index("local_timestamp")
            else:
                value = row[local_index]
                if first_local_timestamp is None:
                    first_local_timestamp = int(value)
                last_local_timestamp = int(value)
            if len(sample_lines) < 6:
                sample_lines.append(",".join(row))
            row_count += 1
    if header is None or row_count < 2:
        raise RuntimeError(f"empty or header-only gzip file {path}")
    sample_path.write_text("\n".join(sample_lines) + "\n", encoding="utf-8")
    return {
        "row_count_including_header": row_count,
        "data_row_count": row_count - 1,
        "columns": header,
        "first_local_timestamp": first_local_timestamp,
        "last_local_timestamp": last_local_timestamp,
        "local_span_hours": (
            (last_local_timestamp - first_local_timestamp) / 3_600_000_000
            if first_local_timestamp is not None and last_local_timestamp is not None
            else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--dates", nargs="+", default=["2026-03-05"])
    args = parser.parse_args()
    if not args.source.exists():
        raise FileNotFoundError(args.source)
    args.output.mkdir(parents=True, exist_ok=True)
    raw = args.cache / "tardis" / EXCHANGE / DATE / SYMBOL

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for data_type in DATA_TYPES:
        url = dataset_url(data_type)
        path = raw / f"{data_type}.csv.gz"
        print(f"INDEPENDENT_SAMPLE {data_type} {url}", flush=True)
        try:
            source = download(url, path)
            inspected = inspect_gzip(path, args.output / f"{data_type}_head.csv")
            rows.append(
                {
                    "exchange": EXCHANGE,
                    "symbol": SYMBOL,
                    "date": DATE,
                    "data_type": data_type,
                    **source,
                    **inspected,
                }
            )
        except Exception as exc:
            failures.append({"data_type": data_type, "url": url, "error": repr(exc)})

    payload = {
        "study": "L2_INDEPENDENT_SINGLE_SAMPLE_INTEGRITY_V1",
        "source_description": "Tardis normalized tick CSV exported from captured exchange WebSocket feeds",
        "availability_clock": "local_timestamp",
        "equal_timestamp_tiebreak": "original CSV row order",
        "strategy_outcomes_opened": False,
        "orders_simulated": False,
        "rows": rows,
        "failures": failures,
    }
    (args.output / "alignment_audit.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    flattened = []
    for row in rows:
        flattened.append(
            {
                key: value
                for key, value in row.items()
                if key not in {"columns"}
            }
        )
    with (args.output / "alignment_audit.csv").open("w", newline="", encoding="utf-8") as handle:
        if flattened:
            writer = csv.DictWriter(handle, fieldnames=list(flattened[0]))
            writer.writeheader()
            writer.writerows(flattened)
    summary = {
        "available_count": len(rows),
        "failure_count": len(failures),
        "total_compressed_bytes": sum(int(row["compressed_bytes"]) for row in rows),
        "total_data_rows": sum(int(row["data_row_count"]) for row in rows),
        "strategy_outcomes_opened": False,
        "orders_simulated": False,
    }
    (args.output / "independent_sample_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if len(rows) == len(DATA_TYPES) and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
