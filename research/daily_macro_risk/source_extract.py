from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.request
from pathlib import Path

SERIES = {
    "VIXCLS": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS&cosd=2020-01-01&coed=2023-12-31",
    "DTWEXBGS": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS&cosd=2020-01-01&coed=2023-12-31",
    "DGS10": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd=2020-01-01&coed=2023-12-31",
}


def download(series: str, url: str) -> tuple[bytes, list[dict[str, str]]]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SMC_ICT_2_LIVE-daily-macro-risk/1.0"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = response.read()
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    fields = reader.fieldnames or []
    if len(fields) != 2 or fields[1] != series:
        raise RuntimeError(f"unexpected {series} columns: {fields}")
    date_column = fields[0]
    rows = []
    for row in reader:
        day = str(row[date_column])
        if not ("2020-01-01" <= day <= "2023-12-31"):
            raise RuntimeError(f"out-of-contract date in {series}: {day}")
        rows.append({"date": day, series: str(row[series])})
    if not rows:
        raise RuntimeError(f"empty FRED series {series}")
    return payload, rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for series, url in SERIES.items():
        payload, rows = download(series, url)
        output = args.output_dir / f"{series}_2020_2023.csv"
        with output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("date", series), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        records.append(
            {
                "series": series,
                "url": url,
                "raw_sha256": hashlib.sha256(payload).hexdigest(),
                "raw_bytes": len(payload),
                "filtered_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "filtered_rows": len(rows),
                "first_date": rows[0]["date"],
                "last_date": rows[-1]["date"],
            }
        )

    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260730-DAILY-MACRO-RISK-CORE-001",
        "records": records,
        "availability_rule": "observation date d becomes actionable no earlier than d+2 00:00 UTC",
        "maximum_forward_fill_calendar_days": 5,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    (args.output_dir / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
