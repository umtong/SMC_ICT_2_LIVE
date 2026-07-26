from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIX_ROOT = REPO_ROOT / "sourcefix" / "ml_hl_liquidation_convert_ref_20260726"
sys.path.insert(0, str(FIX_ROOT))

import run_fixed_source_gate as fixed  # noqa: E402

CORRECTION_007 = FIX_ROOT / "CORRECTION_007_STRUCTURED_EVENTS_LIST_BEFORE_MARKET.json"


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_structured_queries(urls: list[str], paths: list[str]) -> tuple[str, str]:
    """Query the observed LIST<STRUCT> events column without string coercion."""
    fixed._load_correction(CORRECTION_007)
    url_list = "[" + ",".join(sql_string(value) for value in urls) + "]"
    path_list = "(" + ",".join(sql_string(value) for value in paths) + ")"
    source = f"read_parquet({url_list}, union_by_name=true)"
    coverage = f"""
        SELECT
            _src,
            count(*)::BIGINT AS row_count,
            min(block_number)::BIGINT AS block_min,
            max(block_number)::BIGINT AS block_max,
            CAST(min(local_time) AS VARCHAR) AS local_time_min,
            CAST(max(local_time) AS VARCHAR) AS local_time_max,
            sum(CASE WHEN COALESCE(list_count(events), 0) > 0 THEN 1 ELSE 0 END)::BIGINT AS nonempty_event_rows
        FROM {source}
        WHERE _src IN {path_list}
        GROUP BY _src
        ORDER BY _src
    """.strip()
    events = f"""
        SELECT
            CAST(local_time AS VARCHAR) AS local_time,
            CAST(block_time AS VARCHAR) AS block_time,
            block_number::BIGINT AS block_number,
            events,
            _src
        FROM {source}
        WHERE _src IN {path_list}
          AND COALESCE(list_count(events), 0) > 0
        ORDER BY local_time, block_number, _src
    """.strip()
    return coverage, events


fixed.engine.build_queries = build_structured_queries


if __name__ == "__main__":
    raise SystemExit(fixed.engine.main())
