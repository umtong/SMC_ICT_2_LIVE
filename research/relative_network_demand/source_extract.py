from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.request
from datetime import date
from pathlib import Path

SOURCES = {
    "BTCUSDT": ("https://raw.githubusercontent.com/coinmetrics/data/master/csv/btc.csv", "5e50f336d268e1f3a38e9885b5aaef36de529700"),
    "ETHUSDT": ("https://raw.githubusercontent.com/coinmetrics/data/master/csv/eth.csv", "d8e4f389b37626f432a923805e5cc5fa2ad5490b"),
}
COLUMNS = ("time", "FeeTotNtv", "TxCnt", "TxTfrCnt", "AdrActCnt", "AssetCompletionTime", "AssetEODCompletionTime")
START = date.fromisoformat("2020-01-01")
END = date.fromisoformat("2023-12-31")


def blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", type=Path, required=True); args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for symbol, (url, expected) in SOURCES.items():
        req = urllib.request.Request(url, headers={"User-Agent": "SMC_ICT_2_LIVE-relative-network-demand/1.0"})
        with urllib.request.urlopen(req, timeout=180) as response: payload = response.read()
        observed = blob_sha(payload)
        if observed != expected: raise RuntimeError(f"{symbol} blob changed: {observed} != {expected}")
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing: raise RuntimeError(f"{symbol} missing {missing}")
        rows=[]
        for row in reader:
            d=date.fromisoformat(row["time"])
            if START <= d <= END: rows.append({c:row.get(c,"") for c in COLUMNS})
        if len(rows) != (END-START).days+1: raise RuntimeError(f"{symbol} row count {len(rows)}")
        output=args.output_dir/f"{symbol}_2020_2023.csv"
        with output.open("w",encoding="utf-8",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=COLUMNS,lineterminator="\n");writer.writeheader();writer.writerows(rows)
        raw=output.read_bytes()
        manifest.append({"symbol":symbol,"source_url":url,"git_blob_sha1":observed,"source_sha256":hashlib.sha256(payload).hexdigest(),"filtered_sha256":hashlib.sha256(raw).hexdigest(),"rows":len(rows)})
    result={"schema_version":1,"claim_id":"CLM-20260730-RELATIVE-NETWORK-DEMAND-CORE-001","availability_delay_hours":48,"records":manifest,"official_2024_2026_opened":False,"orders_submitted":False}
    (args.output_dir/"SOURCE_MANIFEST.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,indent=2,sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())
