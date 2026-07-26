from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


TIMESTAMP_HINTS = ("time", "date", "expiry", "expiration", "maturity")
CATEGORICAL_HINTS = (
    "symbol",
    "instrument",
    "asset",
    "currency",
    "type",
    "option",
    "call",
    "put",
    "exchange",
)
NUMERIC_HINTS = (
    "strike",
    "delta",
    "gamma",
    "vega",
    "theta",
    "rho",
    "iv",
    "vol",
    "price",
    "open_interest",
    "oi",
    "bid",
    "ask",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scalar_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, (str, int, bool)):
        return value
    try:
        return value.as_py()
    except AttributeError:
        return str(value)


def row_json(row: dict[str, Any]) -> dict[str, Any]:
    return {key: scalar_json(value) for key, value in row.items()}


def safe_min_max(array: pa.ChunkedArray) -> dict[str, Any]:
    result: dict[str, Any] = {
        "length": len(array),
        "null_count": array.null_count,
        "type": str(array.type),
    }
    try:
        mm = pc.min_max(array).as_py()
        result["min"] = scalar_json(mm.get("min"))
        result["max"] = scalar_json(mm.get("max"))
    except Exception as exc:
        result["min_max_error"] = repr(exc)
    return result


def inspect_column(parquet_path: Path, name: str, data_type: pa.DataType) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "type": str(data_type)}
    try:
        table = pq.read_table(parquet_path, columns=[name], use_threads=True)
        array = table.column(0)
        out.update(safe_min_max(array))
        lower = name.lower()
        if pa.types.is_string(data_type) or pa.types.is_large_string(data_type) or pa.types.is_dictionary(data_type):
            unique = pc.unique(array)
            out["unique_count"] = len(unique)
            out["sample_unique"] = [scalar_json(item) for item in unique.slice(0, 30).to_pylist()]
        elif any(hint in lower for hint in CATEGORICAL_HINTS):
            unique = pc.unique(array)
            out["unique_count"] = len(unique)
            out["sample_unique"] = [scalar_json(item) for item in unique.slice(0, 30).to_pylist()]
    except Exception as exc:
        out["inspection_error"] = repr(exc)
    return out


def metadata_json(metadata: dict[bytes, bytes] | None) -> dict[str, str]:
    if not metadata:
        return {}
    return {
        key.decode("utf-8", errors="replace"): value.decode("utf-8", errors="replace")
        for key, value in metadata.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    source = args.parquet.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    parquet = pq.ParquetFile(source)
    arrow_schema = parquet.schema_arrow
    names = list(arrow_schema.names)
    report: dict[str, Any] = {
        "schema_version": 1,
        "purpose": "Point-in-time and schema gate only; no outcome, label, action, trade, PnL or model metric is computed.",
        "claim_id": "CLM-20260726-1914-ML-OPTION-SURFACE-001",
        "source": {
            "drive_file_id": "1g9p2Kq8op40y4ZFQQ9AJw8a9CaDThOY8",
            "name": "btc_option_data_toshare.parquet",
            "path": str(source),
            "bytes": source.stat().st_size,
            "sha256": sha256_file(source),
        },
        "parquet": {
            "rows": parquet.metadata.num_rows,
            "row_groups": parquet.num_row_groups,
            "columns": parquet.metadata.num_columns,
            "created_by": parquet.metadata.created_by,
            "serialized_size": parquet.metadata.serialized_size,
            "format_version": parquet.metadata.format_version,
            "key_value_metadata": metadata_json(arrow_schema.metadata),
            "schema": [{"name": field.name, "type": str(field.type), "nullable": field.nullable} for field in arrow_schema],
        },
        "column_profiles": [],
        "row_group_profiles": [],
    }

    selected_columns: list[str] = []
    for field in arrow_schema:
        lower = field.name.lower()
        if (
            any(hint in lower for hint in TIMESTAMP_HINTS)
            or any(hint in lower for hint in CATEGORICAL_HINTS)
            or any(hint in lower for hint in NUMERIC_HINTS)
        ):
            selected_columns.append(field.name)
    # Bound the expensive full-column inspection while prioritizing source semantics.
    selected_columns = selected_columns[:40]
    for name in selected_columns:
        report["column_profiles"].append(inspect_column(source, name, arrow_schema.field(name).type))

    for index in range(parquet.num_row_groups):
        rg = parquet.metadata.row_group(index)
        profile: dict[str, Any] = {
            "index": index,
            "rows": rg.num_rows,
            "total_byte_size": rg.total_byte_size,
            "sorting_columns": [str(item) for item in (rg.sorting_columns or [])],
            "columns": [],
        }
        for column_index in range(min(rg.num_columns, 40)):
            chunk = rg.column(column_index)
            stats = chunk.statistics
            item: dict[str, Any] = {
                "path": chunk.path_in_schema,
                "compression": chunk.compression,
                "encodings": list(chunk.encodings),
                "compressed_size": chunk.total_compressed_size,
                "uncompressed_size": chunk.total_uncompressed_size,
            }
            if stats is not None:
                item["statistics"] = {
                    "null_count": stats.null_count,
                    "distinct_count": stats.distinct_count,
                    "min": scalar_json(stats.min),
                    "max": scalar_json(stats.max),
                }
            profile["columns"].append(item)
        report["row_group_profiles"].append(profile)

    sample_columns = names[: min(len(names), 30)]
    first = parquet.read_row_group(0, columns=sample_columns).slice(0, 10).to_pylist()
    last_group = parquet.read_row_group(parquet.num_row_groups - 1, columns=sample_columns)
    last_start = max(0, last_group.num_rows - 10)
    last = last_group.slice(last_start, 10).to_pylist()
    report["first_rows"] = [row_json(row) for row in first]
    report["last_rows"] = [row_json(row) for row in last]

    lower_names = {name.lower(): name for name in names}
    required_groups = {
        "timestamp": [name for name in names if any(hint in name.lower() for hint in ("time", "date"))],
        "instrument_or_symbol": [name for name in names if any(hint in name.lower() for hint in ("symbol", "instrument"))],
        "expiry": [name for name in names if any(hint in name.lower() for hint in ("expiry", "expiration", "maturity"))],
        "strike": [name for name in names if "strike" in name.lower()],
        "option_type": [name for name in names if name.lower() in {"type", "option_type", "call_put", "cp"} or "option_type" in name.lower()],
        "delta": [name for name in names if "delta" in name.lower()],
        "iv": [name for name in names if "iv" in name.lower() or "volatility" in name.lower()],
        "underlying": [name for name in names if "underlying" in name.lower() or name.lower() in {"spot", "index_price"}],
        "open_interest": [name for name in names if "open_interest" in name.lower() or name.lower() == "oi"],
    }
    report["required_group_matches"] = required_groups
    required_core = ("timestamp", "instrument_or_symbol", "expiry", "strike", "option_type", "delta", "iv", "underlying")
    report["schema_gate_core_pass"] = all(required_groups[group] for group in required_core)
    report["contains_btc_hint"] = any("btc" in str(value).lower() for row in report["first_rows"] + report["last_rows"] for value in row.values())
    report["contains_eth_hint"] = any("eth" in str(value).lower() for row in report["first_rows"] + report["last_rows"] for value in row.values())

    output = args.output / "PUBLIC_PARQUET_PROBE.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(output.read_text(encoding="utf-8"))
    # Phase 0 workflow itself succeeds even when the schema gate fails, so the
    # evidence artifact is always preserved. Scientific status is in the JSON.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
