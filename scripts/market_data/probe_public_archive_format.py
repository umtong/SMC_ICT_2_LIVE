#!/usr/bin/env python3
"""Capture exact schemas for the official Bybit public archive formats."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

SAMPLES = {
    "kline_1m": "https://public.bybit.com/kline_for_metatrader4/BTCUSDT/2024/BTCUSDT_1_2024-01-01_2024-01-31.csv.gz",
    "trade_daily": "https://public.bybit.com/trading/XRPUSDT/XRPUSDT2025-01-01.csv.gz",
}


def unwrap_gzip(data: bytes) -> tuple[bytes, int]:
    layers = 0
    while data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)
        layers += 1
    return data, layers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "SMC_ICT_2_LIVE archive format probe/1"})
    records = []
    for name, url in SAMPLES.items():
        response = session.get(url, timeout=180)
        response.raise_for_status()
        raw = response.content
        decoded, layers = unwrap_gzip(raw)
        text = decoded.decode("utf-8", errors="strict")
        lines = text.splitlines()[:5]
        records.append({
            "name": name,
            "url": url,
            "http_status": response.status_code,
            "http_headers": {
                "content_type": response.headers.get("Content-Type"),
                "content_encoding": response.headers.get("Content-Encoding"),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
            },
            "downloaded_bytes": len(raw),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "gzip_layers": layers,
            "decoded_bytes": len(decoded),
            "first_lines": lines,
        })

    result = {
        "schema_version": 1,
        "probe_id": "PROBE-BYBIT-PUBLIC-ARCHIVE-FORMATS-20260727-R1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    path = args.out / "FORMAT_PROBE.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out / "FORMAT_PROBE.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
