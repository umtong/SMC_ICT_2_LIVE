#!/usr/bin/env python3
"""Probe official Bybit mainnet hostnames for public market-data reachability."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

HOSTS = (
    "https://api.bybit.com",
    "https://api.bytick.com",
    "https://api.bybit.nl",
    "https://api.bybit.tr",
    "https://api.bybit.kz",
    "https://api.bybitgeorgia.ge",
    "https://api.bybit.ae",
    "https://api.bybit.eu",
    "https://api.bybit.id",
    "https://api.manepa.jp",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    records = []
    for host in HOSTS:
        url = f"{host}/v5/market/funding/history"
        params = {"category": "linear", "symbol": "BTCUSDT", "limit": 1}
        try:
            response = requests.get(url, params=params, timeout=args.timeout)
            raw = response.content
            record = {
                "host": host,
                "url": response.url,
                "http_status": response.status_code,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "content_type": response.headers.get("Content-Type"),
                "server": response.headers.get("Server"),
            }
            try:
                payload = response.json()
                record["ret_code"] = payload.get("retCode")
                record["ret_msg"] = payload.get("retMsg")
                result = payload.get("result", {}) if isinstance(payload, dict) else {}
                rows = result.get("list", []) if isinstance(result, dict) else []
                record["rows"] = len(rows) if isinstance(rows, list) else None
                record["sample"] = rows[0] if isinstance(rows, list) and rows else None
            except ValueError:
                record["body_prefix"] = raw[:300].decode("utf-8", errors="replace")
            records.append(record)
        except Exception as exc:
            records.append({
                "host": host,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })

    usable = [
        row for row in records
        if row.get("http_status") == 200 and row.get("ret_code") == 0 and row.get("rows", 0) >= 1
    ]
    result = {
        "schema_version": 1,
        "probe_id": "PROBE-BYBIT-OFFICIAL-PUBLIC-HOSTS-20260727-R1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "usable_hosts": [row["host"] for row in usable],
        "records": records,
    }
    path = args.out / "OFFICIAL_HOST_PROBE.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out / "OFFICIAL_HOST_PROBE.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
