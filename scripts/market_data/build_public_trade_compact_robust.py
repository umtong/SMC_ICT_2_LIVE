#!/usr/bin/env python3
"""Build V3 sparse 500 ms shards from Bybit archives with causal external ordering.

Some historical Bybit daily CSV files are not monotonically ordered by their
exchange timestamp. This builder preserves every row and reconstructs event
order by `(exchange_timestamp_us, original_file_row_number)`. It aggregates
chunks independently, then merges overlapping 500 ms buckets with the same
ordering keys, so the result is exact without loading an entire high-volume day
into memory.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from . import build_public_trade_compact as base
    from .canonical_spec import sha256_file
except ImportError:  # direct script execution
    import build_public_trade_compact as base
    from canonical_spec import sha256_file


def _aggregate_chunk(
    chunk: pd.DataFrame,
    path: Path,
    *,
    row_base: int,
) -> tuple[pd.DataFrame, int]:
    required = ["timestamp", "side", "size", "price"]
    if chunk[required].isna().any().any():
        raise ValueError(f"null source value in {path}")
    side = chunk["side"].astype("string").str.casefold()
    valid_side = side.isin(["buy", "sell"])
    if not valid_side.all():
        invalid = sorted(set(side[~valid_side].dropna().tolist()))
        raise ValueError(f"unsupported trade side in {path}: {invalid[:10]}")

    timestamp = chunk["timestamp"].to_numpy(dtype="float64")
    timestamp_us = np.floor(timestamp * 1_000_000.0 + 1e-4).astype("int64")
    if (timestamp_us < 0).any():
        raise ValueError(f"negative exchange timestamp in {path}")
    sequence = np.arange(row_base, row_base + len(chunk), dtype="int64")
    regressions = int(np.count_nonzero(np.diff(timestamp_us) < 0))
    order = np.lexsort((sequence, timestamp_us))
    timestamp_us = timestamp_us[order]
    sequence = sequence[order]
    side_array = side.to_numpy()[order]
    size = chunk["size"].to_numpy(dtype="float64")[order]
    price = chunk["price"].to_numpy(dtype="float64")[order]
    if not np.isfinite(size).all() or not np.isfinite(price).all():
        raise ValueError(f"non-finite price or size in {path}")
    if (size < 0).any() or (price <= 0).any():
        raise ValueError(f"non-positive price or negative size in {path}")

    timestamp_ms = timestamp_us // 1_000
    bucket_ms = (timestamp_ms // 500) * 500
    offset_ms = (timestamp_ms - bucket_ms).astype("int16")
    turnover = size * price
    buy = side_array == "buy"
    enriched = pd.DataFrame({
        "start_time_ms": bucket_ms,
        "event_time_us": timestamp_us,
        "event_sequence": sequence,
        "price": price,
        "size": size,
        "turnover": turnover,
        "buy_volume": np.where(buy, size, 0.0),
        "sell_volume": np.where(~buy, size, 0.0),
        "buy_turnover": np.where(buy, turnover, 0.0),
        "sell_turnover": np.where(~buy, turnover, 0.0),
        "offset_ms": offset_ms,
    })
    grouped = enriched.groupby("start_time_ms", sort=True, observed=True)
    out = grouped.agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("size", "sum"),
        turnover=("turnover", "sum"),
        trade_count=("price", "size"),
        buy_volume=("buy_volume", "sum"),
        sell_volume=("sell_volume", "sum"),
        buy_turnover=("buy_turnover", "sum"),
        sell_turnover=("sell_turnover", "sum"),
        open_time_us=("event_time_us", "first"),
        open_sequence=("event_sequence", "first"),
        close_time_us=("event_time_us", "last"),
        close_sequence=("event_sequence", "last"),
        first_offset_ms=("offset_ms", "first"),
        last_offset_ms=("offset_ms", "last"),
    ).reset_index()

    high_rows = enriched.loc[
        grouped["price"].idxmax(),
        ["start_time_ms", "event_time_us", "event_sequence", "offset_ms"],
    ].rename(columns={
        "event_time_us": "high_time_us",
        "event_sequence": "high_sequence",
        "offset_ms": "high_offset_ms",
    })
    low_rows = enriched.loc[
        grouped["price"].idxmin(),
        ["start_time_ms", "event_time_us", "event_sequence", "offset_ms"],
    ].rename(columns={
        "event_time_us": "low_time_us",
        "event_sequence": "low_sequence",
        "offset_ms": "low_offset_ms",
    })
    out = out.merge(high_rows, on="start_time_ms", how="left", validate="one_to_one")
    out = out.merge(low_rows, on="start_time_ms", how="left", validate="one_to_one")
    return out, regressions


def aggregate_trade_file_robust(
    path: Path,
    *,
    chunksize: int,
) -> tuple[pd.DataFrame, int]:
    parts: list[pd.DataFrame] = []
    total_rows = 0
    total_regressions = 0
    reader = pd.read_csv(
        path,
        compression="gzip",
        usecols=["timestamp", "side", "size", "price"],
        dtype={
            "timestamp": "float64",
            "side": "string",
            "size": "float64",
            "price": "float64",
        },
        chunksize=chunksize,
        on_bad_lines="error",
    )
    for chunk in reader:
        if chunk.empty:
            continue
        part, regressions = _aggregate_chunk(chunk, path, row_base=total_rows)
        parts.append(part)
        total_regressions += regressions
        total_rows += len(chunk)
    if not parts:
        columns = [
            "start_time_ms", "open", "high", "low", "close",
            "volume", "turnover", "trade_count",
            "buy_volume", "sell_volume", "buy_turnover", "sell_turnover",
            "first_offset_ms", "high_offset_ms", "low_offset_ms", "last_offset_ms",
        ]
        return pd.DataFrame(columns=columns), total_rows

    partial = pd.concat(parts, ignore_index=True)
    grouped = partial.groupby("start_time_ms", sort=True, observed=True)
    totals = grouped.agg(
        volume=("volume", "sum"),
        turnover=("turnover", "sum"),
        trade_count=("trade_count", "sum"),
        buy_volume=("buy_volume", "sum"),
        sell_volume=("sell_volume", "sum"),
        buy_turnover=("buy_turnover", "sum"),
        sell_turnover=("sell_turnover", "sum"),
    ).reset_index()

    opens = (
        partial.sort_values(
            ["start_time_ms", "open_time_us", "open_sequence"],
            kind="stable",
        )
        .drop_duplicates("start_time_ms", keep="first")
        [["start_time_ms", "open", "first_offset_ms"]]
    )
    closes = (
        partial.sort_values(
            ["start_time_ms", "close_time_us", "close_sequence"],
            kind="stable",
        )
        .drop_duplicates("start_time_ms", keep="last")
        [["start_time_ms", "close", "last_offset_ms"]]
    )
    highs = (
        partial.sort_values(
            ["start_time_ms", "high", "high_time_us", "high_sequence"],
            ascending=[True, False, True, True],
            kind="stable",
        )
        .drop_duplicates("start_time_ms", keep="first")
        [["start_time_ms", "high", "high_offset_ms"]]
    )
    lows = (
        partial.sort_values(
            ["start_time_ms", "low", "low_time_us", "low_sequence"],
            ascending=[True, True, True, True],
            kind="stable",
        )
        .drop_duplicates("start_time_ms", keep="first")
        [["start_time_ms", "low", "low_offset_ms"]]
    )
    out = totals.merge(opens, on="start_time_ms", validate="one_to_one")
    out = out.merge(highs, on="start_time_ms", validate="one_to_one")
    out = out.merge(lows, on="start_time_ms", validate="one_to_one")
    out = out.merge(closes, on="start_time_ms", validate="one_to_one")
    out = out[[
        "start_time_ms", "open", "high", "low", "close",
        "volume", "turnover", "trade_count",
        "buy_volume", "sell_volume", "buy_turnover", "sell_turnover",
        "first_offset_ms", "high_offset_ms", "low_offset_ms", "last_offset_ms",
    ]].sort_values("start_time_ms", kind="stable").reset_index(drop=True)
    out.attrs["source_timestamp_regressions"] = total_regressions
    return out, total_rows


def code_identity() -> dict[str, str | None]:
    repo = Path(__file__).resolve().parents[2]
    targets = {
        "robust_compact_builder_sha256": repo / "scripts/market_data/build_public_trade_compact_robust.py",
        "base_compact_builder_sha256": repo / "scripts/market_data/build_public_trade_compact.py",
        "source_parser_sha256": repo / "scripts/market_data/build_public_trade_month.py",
        "loader_sha256": repo / "scripts/market_data/load_public_trade_compact.py",
        "verifier_sha256": repo / "scripts/market_data/verify_public_trade_compact.py",
        "contract_sha256": repo / "data/contracts/canonical_bybit_usdt_linear_v1.json",
    }
    return {name: sha256_file(path) if path.is_file() else None for name, path in targets.items()}


def main() -> None:
    base.source.aggregate_trade_file = aggregate_trade_file_robust
    base.code_identity = code_identity
    args = base.parse_args()
    output = base.build(args)
    manifest_path = output / "DATASET_MANIFEST.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_ordering"] = (
            "Rows are ordered by exchange_timestamp_us then original_file_row_number before "
            "500 ms aggregation; chunk overlaps are merged using the same keys."
        )
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "DATASET_MANIFEST.sha256").write_text(
            f"{sha256_file(manifest_path)}  {manifest_path.name}\n", encoding="utf-8"
        )
    print(json.dumps({"status": "BUILT", "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
