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
JINA_URLS = (
    "https://r.jina.ai/http://farside.co.uk/bitcoin-etf-flow-all-data/",
    "https://r.jina.ai/https://farside.co.uk/bitcoin-etf-flow-all-data/",
)
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


def select_html_table(raw: bytes) -> pd.DataFrame:
    tables = pd.read_html(io.BytesIO(raw))
    candidates = []
    for table in tables:
        table = table.copy()
        table.columns = [flatten_column(c) for c in table.columns]
        date_col = next((c for c in table.columns if str(c).strip().lower() == "date"), None)
        total_col = next((c for c in table.columns if str(c).strip().lower() == "total"), None)
        if date_col is not None and total_col is not None:
            candidates.append((len(table), table, date_col, total_col))
    if not candidates:
        raise RuntimeError("No HTML table with Date and Total columns was found")
    _, table, date_col, total_col = max(candidates, key=lambda x: x[0])
    return table.rename(columns={date_col: "date", total_col: "total"})


def split_markdown_row(line: str) -> list[str]:
    values = [x.strip() for x in line.strip().strip("|").split("|")]
    return values


def select_markdown_table(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    header_index = None
    header: list[str] = []
    for i, line in enumerate(lines):
        values = split_markdown_row(line)
        lowered = [v.lower() for v in values]
        if "date" in lowered and "total" in lowered and len(values) >= 10:
            header_index = i
            header = values
            break
    if header_index is None:
        raise RuntimeError("No Markdown ETF table header was found")
    rows = []
    for line in lines[header_index + 1:]:
        values = split_markdown_row(line)
        if values and all(re.fullmatch(r":?-{3,}:?", v.replace(" ", "")) for v in values):
            continue
        if not values or not re.fullmatch(r"\d{2}\s+[A-Za-z]{3}\s+\d{4}", values[0]):
            if rows:
                break
            continue
        if len(values) < len(header):
            values += [""] * (len(header) - len(values))
        rows.append(values[:len(header)])
    if not rows:
        raise RuntimeError("Markdown ETF table contained no dated rows")
    table = pd.DataFrame(rows, columns=header)
    date_col = next(c for c in table.columns if c.strip().lower() == "date")
    total_col = next(c for c in table.columns if c.strip().lower() == "total")
    return table.rename(columns={date_col: "date", total_col: "total"})


def fetch_table(session: requests.Session) -> tuple[pd.DataFrame, dict, bytes]:
    attempts = []
    response = session.get(URL, timeout=90)
    attempts.append({"url": URL, "status": response.status_code, "bytes": len(response.content), "sha256": sha256(response.content)})
    if response.status_code == 200:
        try:
            return select_html_table(response.content), {"transport": "direct", "attempts": attempts}, response.content
        except Exception as exc:
            attempts[-1]["parse_error"] = f"{type(exc).__name__}: {exc}"
    for proxy in JINA_URLS:
        proxied = session.get(proxy, timeout=120)
        attempts.append({"url": proxy, "status": proxied.status_code, "bytes": len(proxied.content), "sha256": sha256(proxied.content)})
        if proxied.status_code != 200:
            continue
        try:
            return select_markdown_table(proxied.content), {"transport": "jina_reader", "attempts": attempts}, proxied.content
        except Exception as exc:
            attempts[-1]["parse_error"] = f"{type(exc).__name__}: {exc}"
    raise RuntimeError("Farside source unavailable through direct and Jina transports: " + json.dumps(attempts))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 SMC-ICT-ETF-flow-research/2.0"})
    table, transport, raw = fetch_table(session)
    (args.output / "farside_transport_response.bin").write_bytes(raw)

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
        "source_url": URL,
        "transport": transport,
        "transport_response_bytes": len(raw),
        "transport_response_sha256": sha256(raw),
        "retrieved_final_table": True,
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
            "Jina Reader is used only as an uncredentialed transport fallback when the original page blocks the GitHub runner; the source URL and all response hashes are preserved.",
            "Dash cells remain missing rather than being silently treated as zero; the provider-reported Total column is authoritative for aggregate flow."
        ]
    }
    (args.output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
