#!/usr/bin/env python3
"""Probe official Bybit public REST hosts without opening any market outcome."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

HOSTS = [
    "https://api.bybit.com",
    "https://api.bytick.com",
    "https://api.bybit.nl",
    "https://api.byhkbit.com",
    "https://api.bybit.tr",
    "https://api.bybit.kz",
]
PARAMS = {
    "category": "linear",
    "symbol": "BTCUSDT",
    "interval": "1",
    "start": 1609459200000,
    "end": 1609459259999,
    "limit": 1,
}


def main() -> int:
    records = []
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-2-source-probe/1.0"})
    for host in HOSTS:
        url = f"{host}/v5/market/kline"
        record = {"host": host, "url": url}
        try:
            response = session.get(url, params=PARAMS, timeout=20)
            raw = response.content
            record.update(
                {
                    "http_status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "body_sha256": hashlib.sha256(raw).hexdigest(),
                    "body_prefix": raw[:160].decode("utf-8", errors="replace"),
                }
            )
            try:
                payload = response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict):
                rows = payload.get("result", {}).get("list", []) or []
                record.update(
                    {
                        "ret_code": payload.get("retCode"),
                        "ret_msg": payload.get("retMsg"),
                        "row_count": len(rows),
                        "first_timestamp_ms": int(rows[0][0]) if rows else None,
                    }
                )
            record["usable_public_kline"] = bool(
                response.status_code == 200
                and record.get("ret_code") == 0
                and record.get("row_count", 0) >= 1
            )
        except Exception as exc:
            record.update(
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "usable_public_kline": False,
                }
            )
        records.append(record)
    result = {
        "schema_version": 1,
        "probe_id": "PROBE-20260727-BYBIT-OFFICIAL-REGIONAL-HOSTS-001",
        "claim_id": "CLM-20260727-0245-ML-SWEEP-CROWDING-001",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "market_outcome_opened": False,
        "model_opened": False,
        "pnl_opened": False,
        "orders_submitted": False,
        "request": PARAMS,
        "records": records,
        "usable_hosts": [record["host"] for record in records if record["usable_public_kline"]],
        "status": "PASS" if any(record["usable_public_kline"] for record in records) else "FAIL",
    }
    output = Path("research/results/ml_sweep_crowding/source_host_probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
