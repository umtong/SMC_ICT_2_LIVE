from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dvol_xsec_regime as study

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]
FUNDING_COLUMNS = ["calc_time", "funding_interval_hours", "last_funding_rate"]


def read_nested_csv_compat(raw_zip: bytes, kind: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as inner:
        names = [name for name in inner.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV, got {names}")
        raw = inner.read(names[0])
    columns = FUNDING_COLUMNS if kind == "fundingRate" else KLINE_COLUMNS
    expected_header = columns[0]
    first_field = raw.splitlines()[0].decode(errors="replace").split(",")[0]
    has_header = first_field == expected_header
    frame = pd.read_csv(
        io.BytesIO(raw),
        header=0 if has_header else None,
        names=None if has_header else columns,
    )
    if list(frame.columns) != columns:
        raise ValueError(f"unexpected {kind} schema: {list(frame.columns)}")
    return frame


study._read_nested_csv = read_nested_csv_compat

if __name__ == "__main__":
    study.main()
