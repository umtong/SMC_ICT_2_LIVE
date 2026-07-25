from __future__ import annotations

import argparse
import csv
import json
import re
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
    # The free sample CDN rejects byte-range GETs with 403, while ordinary
    # HEAD/GET requests are the documented access path. Avoid transferring
    # multi-gigabyte L2 files during this feasibility pass.
    completed = subprocess.run(
        [
            "curl",
            "-L",
            "--head",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "180",
            "--user-agent",
            "SMC-ICT-2-LIVE-research/1.0",
            url,
        ],
        text=True,
        capture_output=True,
        timeout=210,
        check=False,
    )
    header_blocks = re.split(r"\r?\n\r?\n", completed.stdout.strip())
    final_block = header_blocks[-1] if header_blocks else ""
    headers: dict[str, str] = {}
    status = None
    for raw in final_block.splitlines():
        if raw.startswith("HTTP/"):
            parts = raw.split()
            status = parts[1] if len(parts) > 1 else None
        elif ":" in raw:
            key, value = raw.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    total_bytes = None
    value = headers.get("content-length")
    if value and value.isdigit():
        total_bytes = int(value)
    return {
        "url": url,
        "ok": completed.returncode == 0 and status is not None and 200 <= int(status) < 400,
        "curl_returncode": completed.returncode,
        "http_status": status,
        "content_type": headers.get("content-type"),
        "content_range": headers.get("content-range"),
        "total_bytes": total_bytes,
        "etag": headers.get("etag"),
        "last_modified": headers.get("last-modified"),
        "accept_ranges": headers.get("accept-ranges"),
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
                "study": "L2_MAKER_TARDIS_SAMPLE_FEASIBILITY_V2",
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
