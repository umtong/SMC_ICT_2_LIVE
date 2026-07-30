#!/usr/bin/env python3
"""Record the immutable Hugging Face Bybit file inventory before outcomes."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

DATASET_ID = "rogerdehe/klines-bybit"


def main() -> int:
    url = f"https://huggingface.co/api/datasets/{DATASET_ID}"
    response = requests.get(url, timeout=30, headers={"User-Agent": "SMC-ICT-2-source-probe/1.0"})
    response.raise_for_status()
    metadata = response.json()
    siblings = sorted(
        item["rfilename"]
        for item in metadata.get("siblings", [])
        if isinstance(item, dict) and isinstance(item.get("rfilename"), str)
    )
    funding = [name for name in siblings if "funding" in name.lower()]
    btc = [name for name in siblings if "btc" in name.lower() and "usdt" in name.lower()]
    eth = [name for name in siblings if "eth" in name.lower() and "usdt" in name.lower()]
    result = {
        "schema_version": 1,
        "inventory_id": "INV-20260727-HF-BYBIT-FILES-001",
        "claim_id": "CLM-20260727-0245-ML-SWEEP-CROWDING-001",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_id": DATASET_ID,
        "dataset_revision": metadata.get("sha"),
        "dataset_last_modified": metadata.get("lastModified"),
        "sibling_count": len(siblings),
        "funding_file_count": len(funding),
        "funding_files": funding,
        "btc_usdt_candidates": btc,
        "eth_usdt_candidates": eth,
        "market_price_opened": False,
        "model_opened": False,
        "pnl_opened": False,
        "orders_submitted": False,
    }
    path = Path("research/results/ml_sweep_crowding/hf_bybit_file_inventory.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "dataset_revision": result["dataset_revision"],
        "sibling_count": result["sibling_count"],
        "funding_file_count": result["funding_file_count"],
        "btc_candidates": len(btc),
        "eth_candidates": len(eth),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
