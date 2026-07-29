#!/usr/bin/env python3
"""Fetch and hash only the CME daily source extension needed after the immutable 2021-2023 artifact."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SYMBOLS = ("BTC=F", "ETH=F")
START_S = 1_704_067_200  # 2024-01-01 00:00:00 UTC
END_S = 1_782_864_000    # 2026-07-01 00:00:00 UTC, exclusive


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fetch(symbol: str) -> tuple[bytes, str]:
    encoded = urllib.parse.quote(symbol, safe="")
    query = urllib.parse.urlencode({
        "period1": START_S,
        "period2": END_S,
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    })
    errors: list[str] = []
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{encoded}?{query}"
        for attempt in range(5):
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 SMC-ICT-2-LIVE-CME-current-contract/1.0",
                    "Accept": "application/json,text/plain,*/*",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    payload = response.read()
                    if response.status != 200:
                        raise RuntimeError(f"HTTP {response.status}")
                    return payload, url
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError) as exc:
                errors.append(f"{url} attempt={attempt + 1}: {type(exc).__name__}: {exc}")
                time.sleep(min(2**attempt, 12))
    raise RuntimeError("Yahoo CME fetch failed: " + " | ".join(errors[-10:]))


def normalize(payload: bytes, symbol: str) -> list[dict[str, Any]]:
    document = json.loads(payload)
    chart = document.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"Yahoo chart error for {symbol}: {chart['error']}")
    results = chart.get("result") or []
    if len(results) != 1:
        raise RuntimeError(f"expected one Yahoo result for {symbol}, got {len(results)}")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quote_blocks = (result.get("indicators") or {}).get("quote") or []
    if len(quote_blocks) != 1:
        raise RuntimeError(f"missing quote block for {symbol}")
    quote = quote_blocks[0]
    rows: list[dict[str, Any]] = []
    for index, raw_timestamp in enumerate(timestamps):
        row: dict[str, Any] = {"timestamp_s": int(raw_timestamp)}
        valid = True
        for field in ("open", "high", "low", "close", "volume"):
            values = quote.get(field) or []
            value = values[index] if index < len(values) else None
            if field == "volume" and value is None:
                value = 0.0
            try:
                number = float(value)
            except (TypeError, ValueError):
                valid = False
                break
            if not math.isfinite(number) or (field != "volume" and number <= 0):
                valid = False
                break
            row[field] = number
        if valid:
            rows.append(row)
    rows.sort(key=lambda item: item["timestamp_s"])
    deduplicated = {int(item["timestamp_s"]): item for item in rows}
    rows = [deduplicated[key] for key in sorted(deduplicated)]
    if len(rows) < 500:
        raise RuntimeError(f"insufficient 2024-2026 CME rows for {symbol}: {len(rows)}")
    if rows[0]["timestamp_s"] > START_S + 7 * 86_400:
        raise RuntimeError(f"CME source starts too late for {symbol}: {rows[0]['timestamp_s']}")
    if rows[-1]["timestamp_s"] < END_S - 7 * 86_400:
        raise RuntimeError(f"CME source ends too early for {symbol}: {rows[-1]['timestamp_s']}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "source": "Yahoo Finance public v8 chart endpoint",
        "requested_start_s": START_S,
        "requested_end_exclusive_s": END_S,
        "symbols": [],
        "orders_submitted": False,
    }
    for symbol in SYMBOLS:
        payload, url = fetch(symbol)
        safe = symbol.replace("=", "_")
        raw_path = args.out / f"yahoo_{safe}_2024_2026.json"
        raw_path.write_bytes(payload)
        rows = normalize(payload, symbol)
        csv_path = args.out / f"yahoo_{safe}_2024_2026.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp_s", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerows(rows)
        manifest["symbols"].append({
            "symbol": symbol,
            "requested_url": url,
            "rows": len(rows),
            "first_timestamp_s": rows[0]["timestamp_s"],
            "last_timestamp_s": rows[-1]["timestamp_s"],
            "raw_sha256": sha256_bytes(payload),
            "normalized_sha256": sha256_bytes(csv_path.read_bytes()),
            "raw_bytes": len(payload),
        })
    manifest_path = args.out / "CME_SOURCE_EXTENSION_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out / "CME_SOURCE_EXTENSION_MANIFEST.sha256").write_text(
        sha256_bytes(manifest_path.read_bytes()) + "  CME_SOURCE_EXTENSION_MANIFEST.json\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
