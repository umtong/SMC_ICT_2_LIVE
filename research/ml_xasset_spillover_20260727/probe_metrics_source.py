#!/usr/bin/env python3
"""Probe only pre-2024 Binance Vision futures metrics source semantics."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import requests

DATE = "2023-01-03"
MONTH = "2023-01"
CANDIDATES = [
    (
        "USD-M daily BTCUSDT",
        f"https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{DATE}.zip",
    ),
    (
        "USD-M monthly BTCUSDT",
        f"https://data.binance.vision/data/futures/um/monthly/metrics/BTCUSDT/BTCUSDT-metrics-{MONTH}.zip",
    ),
    (
        "COIN-M daily BTCUSD_PERP",
        f"https://data.binance.vision/data/futures/cm/daily/metrics/BTCUSD_PERP/BTCUSD_PERP-metrics-{DATE}.zip",
    ),
    (
        "COIN-M monthly BTCUSD_PERP",
        f"https://data.binance.vision/data/futures/cm/monthly/metrics/BTCUSD_PERP/BTCUSD_PERP-metrics-{MONTH}.zip",
    ),
]


def inspect_zip(payload: bytes) -> dict[str, object]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
        csv_names = [name for name in names if name.lower().endswith(".csv")]
        if len(csv_names) != 1:
            return {"members": names, "error": "expected exactly one CSV"}
        text = zf.read(csv_names[0]).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    return {
        "members": names,
        "row_count": len(rows),
        "first_rows": rows[:4],
    }


def main() -> None:
    out: list[dict[str, object]] = []
    for label, url in CANDIDATES:
        response = requests.get(url, timeout=60)
        record: dict[str, object] = {
            "label": label,
            "url": url,
            "status": response.status_code,
            "bytes": len(response.content),
            "content_type": response.headers.get("content-type"),
        }
        if response.status_code == 200:
            record["archive"] = inspect_zip(response.content)
        else:
            record["body_prefix"] = response.text[:200]
        print(json.dumps(record, ensure_ascii=False), flush=True)
        out.append(record)
    if not any(item["status"] == 200 for item in out):
        raise SystemExit("no candidate metrics archive exists")
    path = Path("artifact/metrics_source_probe.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
