#!/usr/bin/env python3
"""Inspect every numeric funding-mirror column before economic use."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

DATASET_ID = "rogerdehe/klines-bybit"
FILES = {
    "BTCUSDT": "futures/1h/BTC_USDT_USDT-funding_rate.parquet",
    "ETHUSDT": "futures/1h/ETH_USDT_USDT-funding_rate.parquet",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-2-source-probe/1.0"})
    metadata = session.get(
        f"https://huggingface.co/api/datasets/{DATASET_ID}", timeout=30
    ).json()
    revision = metadata["sha"]
    records = []
    for symbol, repository_path in FILES.items():
        encoded = quote(repository_path, safe="/")
        url = f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{revision}/{encoded}?download=true"
        local = Path(".cache/ml_sweep_crowding/hf_bybit_funding") / revision / Path(repository_path).name
        local.parent.mkdir(parents=True, exist_ok=True)
        if not local.exists():
            response = session.get(url, timeout=120, allow_redirects=True)
            response.raise_for_status()
            local.write_bytes(response.content)
        frame = pd.read_parquet(local)
        summaries = {}
        for column in frame.columns:
            numeric = pd.to_numeric(frame[column], errors="coerce")
            if numeric.notna().sum() == 0:
                continue
            summaries[str(column)] = {
                "non_null": int(numeric.notna().sum()),
                "unique": int(numeric.nunique(dropna=True)),
                "min": float(numeric.min()),
                "max": float(numeric.max()),
                "zero_share": float((numeric.fillna(0) == 0).mean()),
            }
        records.append(
            {
                "symbol": symbol,
                "repository_path": repository_path,
                "file_sha256": sha256_file(local),
                "rows": int(len(frame)),
                "columns": [str(column) for column in frame.columns],
                "numeric_summaries": summaries,
                "first_rows": frame.head(5).astype(str).to_dict(orient="records"),
                "last_rows": frame.tail(5).astype(str).to_dict(orient="records"),
            }
        )
    result = {
        "schema_version": 1,
        "inspection_id": "INSPECT-20260727-HF-BYBIT-FUNDING-COLUMNS-001",
        "claim_id": "CLM-20260727-0245-ML-SWEEP-CROWDING-001",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_id": DATASET_ID,
        "dataset_revision": revision,
        "records": records,
        "market_price_opened": False,
        "model_opened": False,
        "pnl_opened": False,
        "orders_submitted": False,
    }
    out = Path("research/results/ml_sweep_crowding/bybit_funding_column_inspection.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
