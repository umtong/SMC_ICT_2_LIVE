#!/usr/bin/env python3
"""Build a hash-pinned 2023 Binance USD-M one-minute snapshot.

The builder intentionally has no evaluation or model logic. It downloads only
pre-2024 monthly archives and produces one immutable NPZ per allowed symbol plus
an auditable manifest. Post-2023 URLs are rejected by construction.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import requests

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
EXPECTED_STEP_MS = 60_000
CUTOFF_MS = 1_704_067_200_000  # 2024-01-01T00:00:00Z, exclusive


@dataclass(frozen=True)
class SourceRecord:
    symbol: str
    month: str
    url: str
    bytes: int
    sha256: str
    rows: int
    first_open_time_ms: int
    last_open_time_ms: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def month_range(start: str, end: str) -> list[str]:
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    if (sy, sm) > (ey, em):
        raise ValueError("start must not exceed end")
    out: list[str] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    if any(int(x[:4]) >= 2024 for x in out):
        raise ValueError("pre-2024 builder refuses 2024-or-later months")
    return out


def parse_archive(symbol: str, month: str, payload: bytes) -> tuple[SourceRecord, np.ndarray]:
    url = f"{BASE}/{symbol}/1m/{symbol}-1m-{month}.zip"
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(f"{url}: expected one CSV, found {names}")
        raw = zf.read(names[0]).decode("utf-8")

    rows: list[list[float]] = []
    for row in csv.reader(io.StringIO(raw)):
        if not row:
            continue
        try:
            open_time = int(row[0])
        except ValueError:  # tolerate a provider header if one is introduced
            continue
        if len(row) < 11:
            raise RuntimeError(f"{url}: short row with {len(row)} columns")
        rows.append(
            [
                float(open_time),
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[7]),
                float(row[8]),
                float(row[10]),
            ]
        )
    if not rows:
        raise RuntimeError(f"{url}: no parseable rows")
    a = np.asarray(rows, dtype=np.float64)
    t = a[:, 0].astype(np.int64)
    if np.any(t >= CUTOFF_MS):
        raise RuntimeError(f"{url}: post-cutoff observation present")
    if np.any(np.diff(t) <= 0):
        raise RuntimeError(f"{url}: timestamps are not strictly increasing")
    rec = SourceRecord(
        symbol=symbol,
        month=month,
        url=url,
        bytes=len(payload),
        sha256=sha256_bytes(payload),
        rows=len(a),
        first_open_time_ms=int(t[0]),
        last_open_time_ms=int(t[-1]),
    )
    return rec, a


def download_one(symbol: str, month: str, timeout: int) -> tuple[SourceRecord, np.ndarray]:
    url = f"{BASE}/{symbol}/1m/{symbol}-1m-{month}.zip"
    with requests.get(url, timeout=timeout) as response:
        response.raise_for_status()
        return parse_archive(symbol, month, response.content)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(out_dir: Path, months: Iterable[str], workers: int, timeout: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = [(s, m) for s in SYMBOLS for m in months]
    collected: dict[str, list[tuple[SourceRecord, np.ndarray]]] = {s: [] for s in SYMBOLS}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, s, m, timeout): (s, m) for s, m in tasks}
        for fut in as_completed(futures):
            s, m = futures[fut]
            rec, arr = fut.result()
            collected[s].append((rec, arr))
            print(f"downloaded {s} {m}: {rec.rows} rows", flush=True)

    manifest: dict[str, object] = {
        "schema_version": 1,
        "dataset_id": "BINANCE_USDM_4ASSET_1M_2023_XASSET_SPILLOVER_R1",
        "provider": "Binance Vision official public archives",
        "market": "USD-M perpetual futures",
        "symbols": list(SYMBOLS),
        "timeframe": "1m",
        "causal_availability": (
            "A bar is usable only after close. Under the project 500 ms latency and one-minute "
            "resolution, executable evaluation begins no earlier than decision_index + 2 open."
        ),
        "information_cutoff": "2023-12-31T23:59:59.999Z",
        "sources": [],
        "snapshots": [],
    }

    reference_t: np.ndarray | None = None
    for symbol in SYMBOLS:
        parts = sorted(collected[symbol], key=lambda x: x[0].month)
        records = [p[0] for p in parts]
        a = np.vstack([p[1] for p in parts])
        order = np.argsort(a[:, 0], kind="stable")
        a = a[order]
        t = a[:, 0].astype(np.int64)
        if np.any(np.diff(t) != EXPECTED_STEP_MS):
            bad = np.flatnonzero(np.diff(t) != EXPECTED_STEP_MS)
            sample = [(int(t[i]), int(t[i + 1])) for i in bad[:10]]
            raise RuntimeError(f"{symbol}: non-exact one-minute grid; sample={sample}")
        if reference_t is None:
            reference_t = t
        elif not np.array_equal(reference_t, t):
            raise RuntimeError(f"{symbol}: timestamps do not align with first symbol")

        path = out_dir / f"{symbol}_1m_2023.npz"
        np.savez_compressed(
            path,
            open_time_ms=t,
            open=a[:, 1],
            high=a[:, 2],
            low=a[:, 3],
            close=a[:, 4],
            quote_volume=a[:, 5],
            trades=a[:, 6],
            taker_buy_quote=a[:, 7],
        )
        manifest["sources"].extend(asdict(r) for r in records)
        manifest["snapshots"].append(
            {
                "symbol": symbol,
                "path": path.name,
                "rows": int(len(t)),
                "first_open_time_ms": int(t[0]),
                "last_open_time_ms": int(t[-1]),
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )

    manifest_path = out_dir / "DATASET_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "DATASET_MANIFEST.sha256").write_text(
        f"{file_sha256(manifest_path)}  {manifest_path.name}\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(out_dir),
                "rows": int(0 if reference_t is None else len(reference_t)),
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2023-01")
    parser.add_argument("--end", default="2023-12")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    months = month_range(args.start, args.end)
    build(args.out, months, max(1, args.workers), args.timeout)


if __name__ == "__main__":
    main()
