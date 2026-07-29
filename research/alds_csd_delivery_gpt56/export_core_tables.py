#!/usr/bin/env python3
"""Export verified canonical core tables to pandas pickle for local causal research."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

SEGMENTS = (
    "PRE_2024_2021", "PRE_2024_2022", "PRE_2024_2023",
    "2024_H1", "2024_H2", "2025_H1", "2025_H2", "2026_H1",
)
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TABLES = (
    ("trade_bars/5m.parquet", "bars_5m", "start_time_ms"),
    ("trade_bars/15m.parquet", "bars_15m", "start_time_ms"),
    ("trade_bars/1h.parquet", "bars_1h", "start_time_ms"),
    ("trade_bars/4h.parquet", "bars_4h", "start_time_ms"),
    ("trade_bars/1d.parquet", "bars_1d", "start_time_ms"),
    ("streams/open_interest_5m.parquet", "open_interest_5m", "timestamp_ms"),
    ("streams/account_ratio_5m.parquet", "account_ratio_5m", "timestamp_ms"),
    ("streams/funding_events.parquet", "funding_events", "timestamp_ms"),
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def export_symbol(root: Path, out: Path, symbol: str) -> list[dict]:
    evidence: list[dict] = []
    symbol_out = out / symbol
    symbol_out.mkdir(parents=True, exist_ok=True)
    for relative, label, time_col in TABLES:
        parts = []
        for segment in SEGMENTS:
            path = root / symbol / segment / relative
            frame = pd.read_parquet(path)
            frame["segment"] = segment
            parts.append(frame)
        table = pd.concat(parts, ignore_index=True)
        table = table.sort_values(time_col, kind="stable").drop_duplicates(time_col, keep="last").reset_index(drop=True)
        output = symbol_out / f"{label}.pkl.gz"
        table.to_pickle(output, compression="gzip", protocol=5)
        item = {
            "symbol": symbol,
            "table": label,
            "rows": int(len(table)),
            "columns": list(table.columns),
            "first_time_ms": int(table[time_col].iloc[0]) if len(table) else None,
            "last_time_ms": int(table[time_col].iloc[-1]) if len(table) else None,
            "sha256": sha256(output),
            "bytes": output.stat().st_size,
        }
        evidence.append(item)
        print(json.dumps(item, sort_keys=True), flush=True)
        del table, parts
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    evidence = []
    for symbol in SYMBOLS:
        evidence.extend(export_symbol(args.root, args.out, symbol))
    (args.out / "EXPORT_MANIFEST.json").write_text(
        json.dumps({"schema_version": 1, "tables": evidence}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
