#!/usr/bin/env python3
"""Outcome-sealed probe of all currently documented Bybit regional REST hosts."""
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
    "https://api.bybit.tr",
    "https://api.bybit.kz",
    "https://api.bybitgeorgia.ge",
    "https://api.bybit.ae",
    "https://api.bybit.eu",
    "https://api.bybit.id",
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
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-2-source-probe/1.0"})
    records = []
    for host in HOSTS:
        url = f"{host}/v5/market/kline"
        row = {"host": host, "url": url}
        try:
            response = session.get(url, params=PARAMS, timeout=20, allow_redirects=True)
            raw = response.content
            row.update(
                {
                    "http_status": response.status_code,
                    "final_url": response.url,
                    "content_type": response.headers.get("content-type"),
                    "body_sha256": hashlib.sha256(raw).hexdigest(),
                    "body_prefix": raw[:240].decode("utf-8", errors="replace"),
                }
            )
            try:
                payload = response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict):
                data = payload.get("result", {}).get("list", []) or []
                row.update(
                    {
                        "ret_code": payload.get("retCode"),
                        "ret_msg": payload.get("retMsg"),
                        "row_count": len(data),
                        "first_timestamp_ms": int(data[0][0]) if data else None,
                    }
                )
            row["usable_public_kline"] = bool(
                response.status_code == 200
                and row.get("ret_code") == 0
                and row.get("row_count", 0) >= 1
            )
        except Exception as exc:
            row.update(
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "usable_public_kline": False,
                }
            )
        records.append(row)
    usable = [row["host"] for row in records if row["usable_public_kline"]]
    result = {
        "schema_version": 1,
        "probe_id": "PROBE-20260727-BYBIT-OFFICIAL-REGIONAL-HOSTS-002",
        "claim_id": "CLM-20260727-0245-ML-SWEEP-CROWDING-001",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request": PARAMS,
        "records": records,
        "usable_hosts": usable,
        "status": "PASS" if usable else "FAIL",
        "market_outcome_opened": False,
        "model_opened": False,
        "pnl_opened": False,
        "credentials_used": False,
        "orders_submitted": False,
    }
    output = Path("research/results/ml_sweep_crowding/source_host_probe_v2.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
