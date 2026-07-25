from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path

EXCHANGE = "binance-futures"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
DATA_TYPES = ("trades", "book_ticker", "book_snapshot_5", "incremental_book_L2")
DATES = (
    "2023-01-01",
    "2023-07-01",
    "2024-01-01",
    "2024-07-01",
    "2025-01-01",
    "2025-08-01",
    "2026-01-01",
    "2026-04-01",
)


def dataset_url(data_type: str, date: str, symbol: str) -> str:
    year, month, day = date.split("-")
    return (
        f"https://datasets.tardis.dev/v1/{EXCHANGE}/{data_type}/"
        f"{year}/{month}/{day}/{symbol}.csv.gz"
    )


def probe(url: str) -> dict[str, object]:
    # A one-byte ranged GET is more reliable than HEAD across object-storage/CDN paths.
    completed = subprocess.run(
        [
            "curl",
            "-L",
            "--fail",
            "--silent",
            "--show-error",
            "--range",
            "0-0",
            "--dump-header",
            "-",
            "--output",
            "/dev/null",
            url,
        ],
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    headers: dict[str, str] = {}
    for raw in completed.stdout.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    content_range = headers.get("content-range", "")
    total_bytes = None
    if "/" in content_range:
        tail = content_range.rsplit("/", 1)[-1]
        if tail.isdigit():
            total_bytes = int(tail)
    if total_bytes is None:
        value = headers.get("content-length")
        if value and value.isdigit() and int(value) > 1:
            total_bytes = int(value)
    return {
        "url": url,
        "ok": completed.returncode == 0,
        "curl_returncode": completed.returncode,
        "http_status": headers.get("x-http-status", headers.get(":status")),
        "content_type": headers.get("content-type"),
        "content_range": content_range or None,
        "total_bytes": total_bytes,
        "etag": headers.get("etag"),
        "last_modified": headers.get("last-modified"),
        "error": completed.stderr.strip() or None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    for date in DATES:
        for symbol in SYMBOLS:
            for data_type in DATA_TYPES:
                url = dataset_url(data_type, date, symbol)
                print(f"PROBE {date} {symbol} {data_type}", flush=True)
                result = probe(url)
                rows.append(
                    {
                        "date": date,
                        "symbol": symbol,
                        "data_type": data_type,
                        **result,
                    }
                )

    (args.output / "tardis_probe.json").write_text(
        json.dumps(
            {
                "study": "L2_MAKER_TARDIS_SAMPLE_FEASIBILITY_V1",
                "strategy_outcomes_opened": False,
                "orders_simulated": False,
                "rows": rows,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with (args.output / "tardis_probe.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    ok = sum(bool(row["ok"]) for row in rows)
    known_sizes = [int(row["total_bytes"]) for row in rows if row["total_bytes"] is not None]
    summary = {
        "row_count": len(rows),
        "available_count": ok,
        "size_known_count": len(known_sizes),
        "total_known_bytes": sum(known_sizes),
        "strategy_outcomes_opened": False,
        "orders_simulated": False,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
