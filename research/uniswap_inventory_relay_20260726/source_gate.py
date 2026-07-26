from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

CLAIM_ID = "CLM-20260726-2315-ML-UNISWAP-INVENTORY-001"
UNISWAP_DATASET = "arthurneuron/USDC-WETH-Uniswap-V3-2021-to-2023"
BLOCK_DATASET = "vnegi10/Ethereum_blockchain_parquet"
UNISWAP_MIN_BLOCK = 12_376_729
UNISWAP_MAX_BLOCK = 18_700_000
PARQUET_API = f"https://datasets-server.huggingface.co/parquet?dataset={UNISWAP_DATASET}"
BLOCK_META_API = f"https://huggingface.co/api/datasets/{BLOCK_DATASET}"
BLOCK_TREE_API = f"https://huggingface.co/api/datasets/{BLOCK_DATASET}/tree/main/blocks?recursive=true&expand=false&limit=1000"
BYBIT_BASE = "https://public.bybit.com/kline_for_metatrader4"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_json(session: requests.Session, url: str) -> tuple[Any, dict[str, str]]:
    last: Exception | None = None
    for attempt in range(6):
        try:
            response = session.get(url, timeout=(30, 180))
            response.raise_for_status()
            return response.json(), {k.lower(): v for k, v in response.headers.items()}
        except Exception as exc:  # pragma: no cover - network path
            last = exc
            if attempt == 5:
                raise
            time.sleep(min(2**attempt, 20))
    raise RuntimeError(last)


def download(session: requests.Session, url: str, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        tmp = path.with_suffix(path.suffix + ".part")
        last: Exception | None = None
n        for attempt in range(6):
            try:
                with session.get(url, stream=True, timeout=(30, 300), allow_redirects=True) as response:
                    response.raise_for_status()
                    with tmp.open("wb") as handle:
                        for chunk in response.iter_content(1 << 20):
                            if chunk:
                                handle.write(chunk)
                tmp.replace(path)
                break
            except Exception as exc:  # pragma: no cover - network path
                last = exc
                tmp.unlink(missing_ok=True)
                if attempt == 5:
                    raise
                time.sleep(min(2**attempt, 20))
        if last is not None and not path.exists():
            raise last
    return {
        "url": url,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def parquet_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        candidates = payload.get("parquet_files") or payload.get("files") or []
    else:
        candidates = []
    rows: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        filename = item.get("filename") or item.get("path") or (str(url).rsplit("/", 1)[-1] if url else None)
        if url and filename:
            rows.append({**item, "url": str(url), "filename": str(filename)})
    return rows


_BLOCK_RE = re.compile(r"__(\d+)_to_(\d+)\.parquet$")


def relevant_block_entries(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    result = []
    for item in payload:
        if not isinstance(item, dict) or item.get("type") not in {"file", None}:
            continue
        path = str(item.get("path") or "")
        match = _BLOCK_RE.search(path)
        if not match:
            continue
        lo, hi = map(int, match.groups())
        if hi < UNISWAP_MIN_BLOCK or lo > UNISWAP_MAX_BLOCK:
            continue
        result.append({**item, "path": path, "lo": lo, "hi": hi})
    return sorted(result, key=lambda row: row["lo"])


def bybit_month_url(symbol: str, interval: int, year: int, month: int, last_day: int) -> str:
    name = f"{symbol}_{interval}_{year:04d}-{month:02d}-01_{year:04d}-{month:02d}-{last_day:02d}.csv.gz"
    return f"{BYBIT_BASE}/{symbol}/{year}/{name}"


def inspect_bybit(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rb") as handle:
        while handle.read(1 << 20):
            pass
    frame = pd.read_csv(path, compression="gzip", header=None, nrows=5000, low_memory=False)
    if frame.shape[1] < 6:
        raise ValueError(f"Bybit schema has {frame.shape[1]} columns")
    sample = frame.iloc[:, :6].copy()
    sample.columns = ["datetime", "open", "high", "low", "close", "volume"]
    numeric = sample[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    dt = pd.to_datetime(sample["datetime"], utc=True, errors="coerce", format="mixed")
    valid = dt.notna() & numeric.notna().all(axis=1)
    if valid.sum() < 100:
        raise ValueError("Bybit sample has fewer than 100 valid rows")
    return {
        "columns": int(frame.shape[1]),
        "sample_rows": int(len(frame)),
        "valid_sample_rows": int(valid.sum()),
        "sample_start": dt[valid].iloc[0].isoformat(),
        "sample_end": dt[valid].iloc[-1].isoformat(),
    }


def run(output: Path, cache: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-2-uniswap-source-gate/1.0"})

    uni_payload, uni_headers = request_json(session, PARQUET_API)
    uni_entries = parquet_entries(uni_payload)
    if not uni_entries:
        raise RuntimeError("Hugging Face parquet API returned no Uniswap files")

    uni_records = []
    uni_rows = 0
    uni_min_block = None
    uni_max_block = None
    uni_columns: set[str] = set()
    for i, entry in enumerate(uni_entries):
        path = cache / "uniswap" / f"part-{i:03d}.parquet"
        record = download(session, entry["url"], path)
        frame = pd.read_parquet(path, columns=["Block", "USDC", "WETH", "Transactions", "Price"])
        if frame.empty:
            raise ValueError(f"empty Uniswap parquet {entry['filename']}")
        uni_columns.update(frame.columns)
        blocks = pd.to_numeric(frame["Block"], errors="coerce").dropna().astype("int64")
        uni_rows += int(len(frame))
        current_min, current_max = int(blocks.min()), int(blocks.max())
        uni_min_block = current_min if uni_min_block is None else min(uni_min_block, current_min)
        uni_max_block = current_max if uni_max_block is None else max(uni_max_block, current_max)
        record.update({"filename": entry["filename"], "rows": int(len(frame)), "min_block": current_min, "max_block": current_max})
        uni_records.append(record)
    required_uni_columns = {"Block", "USDC", "WETH", "Transactions", "Price"}
    if uni_columns != required_uni_columns:
        raise ValueError(f"unexpected Uniswap columns {sorted(uni_columns)}")
    if uni_rows < 6_000_000 or uni_min_block is None or uni_max_block is None:
        raise ValueError("Uniswap dataset coverage is insufficient")

    block_meta, _ = request_json(session, BLOCK_META_API)
    block_sha = str(block_meta.get("sha") or "main") if isinstance(block_meta, dict) else "main"
    block_tree, block_headers = request_json(session, BLOCK_TREE_API)
    block_entries = relevant_block_entries(block_tree)
    if not block_entries:
        raise RuntimeError("no Ethereum block parquet files overlap Uniswap block range")

    block_records = []
    block_rows = 0
    anchor_min = None
    anchor_max = None
    for entry in block_entries:
        url = f"https://huggingface.co/datasets/{BLOCK_DATASET}/resolve/{block_sha}/{entry['path']}?download=true"
        path = cache / "blocks" / Path(entry["path"]).name
        record = download(session, url, path)
        frame = pd.read_parquet(path, columns=["block_number", "timestamp"])
        if frame.empty:
            continue
        block_number = pd.to_numeric(frame["block_number"], errors="coerce").dropna().astype("int64")
        timestamp = pd.to_numeric(frame["timestamp"], errors="coerce").dropna().astype("int64")
        if block_number.empty or timestamp.empty:
            raise ValueError(f"invalid block timestamp parquet {entry['path']}")
        current_min, current_max = int(block_number.min()), int(block_number.max())
        anchor_min = current_min if anchor_min is None else min(anchor_min, current_min)
        anchor_max = current_max if anchor_max is None else max(anchor_max, current_max)
        block_rows += int(len(frame))
        record.update({"source_path": entry["path"], "rows": int(len(frame)), "min_block": current_min, "max_block": current_max})
        block_records.append(record)
    if anchor_min is None or anchor_max is None or anchor_min > uni_min_block or anchor_max < uni_max_block:
        raise ValueError(f"block anchor coverage {anchor_min}..{anchor_max} does not cover Uniswap {uni_min_block}..{uni_max_block}")

    bybit_specs = [
        ("ETHUSDT", 5, 2021, 7, 31),
        ("ETHUSDT", 5, 2023, 12, 31),
        ("ETHUSDT", 5, 2024, 1, 31),
    ]
    bybit_records = []
    for symbol, interval, year, month, last_day in bybit_specs:
        url = bybit_month_url(symbol, interval, year, month, last_day)
        path = cache / "bybit" / str(year) / url.rsplit("/", 1)[-1]
        record = download(session, url, path)
        record.update({"symbol": symbol, "interval": interval, "year": year, "month": month, **inspect_bybit(path)})
        bybit_records.append(record)

    result = {
        "claim_id": CLAIM_ID,
        "status": "SOURCE_GATE_PASS",
        "decision": "OPEN_FROZEN_PRE2024_MODEL_STAGE",
        "uniswap": {
            "dataset": UNISWAP_DATASET,
            "parquet_api": PARQUET_API,
            "api_etag": uni_headers.get("etag"),
            "file_count": len(uni_records),
            "rows": uni_rows,
            "min_block": uni_min_block,
            "max_block": uni_max_block,
            "records": uni_records,
        },
        "ethereum_blocks": {
            "dataset": BLOCK_DATASET,
            "revision": block_sha,
            "tree_etag": block_headers.get("etag"),
            "file_count": len(block_records),
            "rows": block_rows,
            "min_block": anchor_min,
            "max_block": anchor_max,
            "records": block_records,
        },
        "bybit_probe": bybit_records,
        "outcome_market_data_opened": False,
        "model_fitted": False,
        "strategy_pnl_opened": False,
        "2024_strategy_outcome_opened": False,
        "orders_submitted": False,
    }
    path = output / "SOURCE_GATE.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = output / "SHA256SUMS.txt"
    files = sorted(p for p in output.iterdir() if p.is_file() and p.name != manifest.name)
    manifest.write_text("".join(f"{sha256_file(p)}  {p.name}\n" for p in files), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output, args.cache)
    print(json.dumps({
        "status": result["status"],
        "decision": result["decision"],
        "uniswap_rows": result["uniswap"]["rows"],
        "block_files": result["ethereum_blocks"]["file_count"],
        "bybit_probe_files": len(result["bybit_probe"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
