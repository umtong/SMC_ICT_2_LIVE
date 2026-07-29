#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests

URL = "https://farside.co.uk/bitcoin-etf-flow-all-data/"
END_EXCLUSIVE = pd.Timestamp("2026-07-01T00:00:00Z")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def flatten_column(column) -> str:
    if isinstance(column, tuple):
        values = [str(x).strip() for x in column if str(x).strip() and not str(x).startswith("Unnamed")]
        return values[-1] if values else str(column[-1])
    return str(column).strip()


def parse_number(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "—", "–", "nan", "None"}:
        return np.nan
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = re.sub(r"[^0-9.+-]", "", text)
    if not text:
        return np.nan
    number = float(text)
    return -abs(number) if negative else number


def select_table(raw: bytes) -> pd.DataFrame:
    tables = pd.read_html(io.BytesIO(raw))
    candidates = []
    for table in tables:
        table = table.copy()
        table.columns = [flatten_column(c) for c in table.columns]
        lowered = {str(c).lower(): c for c in table.columns}
        date_col = next((c for c in table.columns if str(c).strip().lower() == "date"), None)
        total_col = next((c for c in table.columns if str(c).strip().lower() == "total"), None)
        if date_col is not None and total_col is not None:
            candidates.append((len(table), table, date_col, total_col))
    if not candidates:
        raise RuntimeError("No Farside table with Date and Total columns was found")
    _, table, date_col, total_col = max(candidates, key=lambda x: x[0])
    table = table.rename(columns={date_col: "date", total_col: "total"})
    return table


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 SMC-ICT-ETF-flow-research/1.0"})
    response = session.get(URL, timeout=90)
    response.raise_for_status()
    raw = response.content
    (args.output / "farside_raw.html").write_bytes(raw)

    table = select_table(raw)
    table["date"] = pd.to_datetime(table["date"], dayfirst=True, errors="coerce", utc=True)
    table = table[table.date.notna()].copy()
    for column in table.columns:
        if column != "date":
            table[column] = table[column].map(parse_number)
    table = table[(table.date >= pd.Timestamp("2024-01-01T00:00:00Z")) & (table.date < END_EXCLUSIVE)]
    table = table.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    table["available_at"] = table.date + pd.Timedelta(days=1)
    table["reported_total"] = table.pop("total")
    fund_columns = [c for c in table.columns if c not in {"date", "available_at", "reported_total"}]
    table["component_sum"] = table[fund_columns].sum(axis=1, min_count=1)
    table["total_difference"] = table.reported_total - table.component_sum
    table["positive_fund_count"] = (table[fund_columns] > 0).sum(axis=1)
    table["negative_fund_count"] = (table[fund_columns] < 0).sum(axis=1)
    table["nonmissing_fund_count"] = table[fund_columns].notna().sum(axis=1)

    csv_path = args.output / "BTC_ETF_FLOWS_2024_2026H1.csv"
    parquet_path = args.output / "BTC_ETF_FLOWS_2024_2026H1.parquet"
    table.to_csv(csv_path, index=False)
    table.to_parquet(parquet_path, index=False)

    difference = table.total_difference.abs().dropna()
    manifest = {
        "schema_version": 1,
        "provider": "Farside Investors",
        "url": URL,
        "retrieved_final_table": True,
        "raw_html_bytes": len(raw),
        "raw_html_sha256": sha256(raw),
        "rows": len(table),
        "start": table.date.min().isoformat() if len(table) else None,
        "end": table.date.max().isoformat() if len(table) else None,
        "availability_rule": "flow dated d becomes usable at 00:00 UTC on d+1",
        "fund_columns": fund_columns,
        "reported_total_nonmissing": int(table.reported_total.notna().sum()),
        "max_absolute_total_component_difference": float(difference.max()) if len(difference) else None,
        "median_absolute_total_component_difference": float(difference.median()) if len(difference) else None,
        "csv_sha256": sha256(csv_path.read_bytes()),
        "parquet_sha256": sha256(parquet_path.read_bytes()),
        "known_limitations": [
            "This is the current final Farside table; historical revisions and original publication timestamps are not reconstructed.",
            "A conservative next-UTC-day availability rule is used for every row.",
            "Dash cells remain missing rather than being silently treated as zero; the provider-reported Total column is authoritative for aggregate flow."
        ]
    }
    (args.output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
