from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "materialized" / "run.py"
EXPECTED_INPUT_SHA256 = "5e5a5c72114ca3774d2a2dbbf1682880be72306a7d604a809ce62f6911ac4e26"
OLD_READ_SHA256 = "fa52400a3bde756062b826fc41f48b833d4b8e94cf5e539ea17f677b7e0117ca"

OLD = '''def _read_csv(path: Path, kind: str) -> pd.DataFrame:
    # Tardis normalized schemas are stable, but select dynamically to fail clearly.
    header = pd.read_csv(path, compression="gzip", nrows=0).columns.tolist()
    required = {
        "book_snapshot_5": ["local_timestamp", "side", "price", "amount"],
        "quotes": ["local_timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"],
        "trades": ["local_timestamp", "side", "price", "amount"],
    }[kind]
    missing = [c for c in required if c not in header]
    if missing:
        raise RuntimeError(f"{path.name}: missing {missing}; header={header}")
    df = pd.read_csv(
        path,
        compression="gzip",
        usecols=required,
        dtype={"local_timestamp": "int64", "side": "category",
               "price": "float64", "amount": "float64",
               "ask_amount": "float64", "ask_price": "float64",
               "bid_price": "float64", "bid_amount": "float64"},
    )
    if not df["local_timestamp"].is_monotonic_increasing:
        df = df.sort_values("local_timestamp", kind="mergesort").reset_index(drop=True)
    return df
'''

NEW = '''def _read_csv(path: Path, kind: str) -> pd.DataFrame:
    # Tardis quotes/trades are long-form. book_snapshot_5 is a wide snapshot
    # with asks[i].price/amount and bids[i].price/amount columns.
    header = pd.read_csv(path, compression="gzip", nrows=0).columns.tolist()

    if kind == "book_snapshot_5":
        level_columns: list[str] = []
        ordered_price_columns: list[str] = []
        ordered_amount_columns: list[str] = []
        ordered_sides: list[str] = []
        for level in range(5):
            for prefix, side in (("asks", "ask"), ("bids", "bid")):
                p = f"{prefix}[{level}].price"
                a = f"{prefix}[{level}].amount"
                level_columns.extend((p, a))
                ordered_price_columns.append(p)
                ordered_amount_columns.append(a)
                ordered_sides.append(side)
        required = ["local_timestamp", *level_columns]
        missing = [c for c in required if c not in header]
        if missing:
            raise RuntimeError(f"{path.name}: missing {missing}; header={header}")
        dtype = {"local_timestamp": "int64"}
        dtype.update({c: "float64" for c in level_columns})
        wide = pd.read_csv(path, compression="gzip", usecols=required, dtype=dtype)
        ts = wide["local_timestamp"].to_numpy(dtype=np.int64)
        prices = wide[ordered_price_columns].to_numpy(dtype=float).reshape(-1)
        amounts = wide[ordered_amount_columns].to_numpy(dtype=float).reshape(-1)
        long_ts = np.repeat(ts, len(ordered_sides))
        long_sides = np.tile(np.asarray(ordered_sides, dtype=object), len(wide))
        valid = (
            np.isfinite(prices) & np.isfinite(amounts)
            & (prices > 0.0) & (amounts > 0.0)
        )
        df = pd.DataFrame({
            "local_timestamp": long_ts[valid],
            "side": pd.Categorical(long_sides[valid], categories=["ask", "bid"]),
            "price": prices[valid],
            "amount": amounts[valid],
        })
    else:
        required = {
            "quotes": ["local_timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"],
            "trades": ["local_timestamp", "side", "price", "amount"],
        }[kind]
        missing = [c for c in required if c not in header]
        if missing:
            raise RuntimeError(f"{path.name}: missing {missing}; header={header}")
        df = pd.read_csv(
            path, compression="gzip", usecols=required,
            dtype={"local_timestamp": "int64", "side": "category",
                   "price": "float64", "amount": "float64",
                   "ask_amount": "float64", "ask_price": "float64",
                   "bid_price": "float64", "bid_amount": "float64"},
        )

    if not df["local_timestamp"].is_monotonic_increasing:
        df = df.sort_values("local_timestamp", kind="mergesort").reset_index(drop=True)
    return df
'''

source = RUN.read_text()
observed = hashlib.sha256(source.encode()).hexdigest()
if observed != EXPECTED_INPUT_SHA256:
    raise RuntimeError(f"unexpected state-corrected run.py SHA-256: {observed}")
if source.count(OLD) != 1:
    raise RuntimeError(f"expected exactly one frozen _read_csv, got {source.count(OLD)}")
if hashlib.sha256(OLD.encode()).hexdigest() != OLD_READ_SHA256:
    raise RuntimeError("embedded old _read_csv identity mismatch")

patched = source.replace(OLD, NEW)
compile(patched, str(RUN), "exec")
RUN.write_text(patched)
patched_sha = hashlib.sha256(patched.encode()).hexdigest()

spec = importlib.util.spec_from_file_location("persistent_wall_wide", RUN)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load wide-schema patched module")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

columns = {"local_timestamp": [1_000_000, 2_000_000]}
for level in range(5):
    for prefix in ("asks", "bids"):
        columns[f"{prefix}[{level}].price"] = [np.nan, np.nan]
        columns[f"{prefix}[{level}].amount"] = [np.nan, np.nan]
columns["asks[0].price"] = [101.0, 102.0]
columns["asks[0].amount"] = [2.0, 3.0]
columns["bids[0].price"] = [100.0, 101.0]
columns["bids[0].amount"] = [4.0, 5.0]

with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "book.csv.gz"
    pd.DataFrame(columns).to_csv(path, index=False, compression="gzip")
    long = mod._read_csv(path, "book_snapshot_5")

if len(long) != 4:
    raise AssertionError(f"wide snapshot expansion row count: {len(long)}")
observed_rows = [
    (int(row.local_timestamp), str(row.side), float(row.price), float(row.amount))
    for row in long.itertuples(index=False)
]
expected_rows = [
    (1_000_000, "ask", 101.0, 2.0),
    (1_000_000, "bid", 100.0, 4.0),
    (2_000_000, "ask", 102.0, 3.0),
    (2_000_000, "bid", 101.0, 5.0),
]
if observed_rows != expected_rows:
    raise AssertionError(f"wide snapshot expansion mismatch: {observed_rows}")

print(json.dumps({
    "patched_run_sha256": patched_sha,
    "wide_book_snapshot_5_test": "PASS",
    "expanded_rows": observed_rows,
}, sort_keys=True))
