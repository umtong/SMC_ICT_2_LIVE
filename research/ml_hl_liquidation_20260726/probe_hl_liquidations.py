from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

import duckdb
import requests

REPOSITORY = "gionuibk/hyperliquid-misc-events"
DATES = (
    "2025-10-06",
    "2025-10-20",
    "2025-11-03",
    "2025-11-17",
    "2025-12-01",
    "2025-12-15",
)
HOURS = (0, 4, 8, 12, 16, 20)
TARGET_COINS = ("BTC", "ETH", "SOL", "XRP")
USER_AGENT = "SMC-ICT-2-HL-liquidation-source-gate/2.0"


class SourceGateError(RuntimeError):
    pass


def stable_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )


def parse_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} is not finite")
    return number


def parse_timestamp(value: Any, field: str) -> str:
    if value is None:
        raise ValueError(f"{field} is missing")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field} is missing")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed.isoformat(timespec="microseconds")


def candidate_paths() -> list[str]:
    return [
        f"misc_events_by_block/hourly/{date.replace('-', '')}/{hour}.lz4"
        for date in DATES
        for hour in HOURS
    ]


def resolve_revision(session: requests.Session) -> tuple[str, dict[str, Any]]:
    url = f"https://huggingface.co/api/datasets/{REPOSITORY}"
    response = session.get(
        url,
        params={"blobs": "true"},
        timeout=(20, 90),
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    metadata = response.json()
    revision = metadata.get("sha")
    if not isinstance(revision, str) or len(revision) < 12:
        raise SourceGateError(
            f"Unable to resolve immutable dataset SHA: {revision!r}"
        )
    return revision, metadata


def find_parquet_siblings(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    siblings = metadata.get("siblings")
    if not isinstance(siblings, list):
        raise SourceGateError("Dataset metadata has no siblings list")
    output: list[dict[str, Any]] = []
    for item in siblings:
        if not isinstance(item, dict):
            continue
        path = item.get("rfilename")
        if isinstance(path, str) and path.startswith("data/") and path.endswith(
            ".parquet"
        ):
            output.append(item)
    if not output:
        raise SourceGateError("No consolidated data/*.parquet sibling found")
    output.sort(key=lambda item: str(item["rfilename"]))
    return output


def revision_url(revision: str, relative_path: str) -> str:
    return (
        f"https://huggingface.co/datasets/{REPOSITORY}/resolve/"
        f"{urllib.parse.quote(revision, safe='')}/"
        f"{urllib.parse.quote(relative_path, safe='/')}?download=true"
    )


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_queries(urls: list[str], paths: list[str]) -> tuple[str, str]:
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
            sum(CASE WHEN events IS NOT NULL AND trim(events) <> '[]' THEN 1 ELSE 0 END)::BIGINT AS nonempty_event_rows
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
          AND events IS NOT NULL
          AND trim(events) <> '[]'
          AND trim(events) <> ''
        ORDER BY local_time, block_number, _src
    """.strip()
    return coverage, events


def connect_duckdb() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(database=":memory:")
    connection.execute("SET threads=4")
    connection.execute("SET memory_limit='6GB'")
    try:
        connection.execute("LOAD httpfs")
    except Exception:
        connection.execute("INSTALL httpfs")
        connection.execute("LOAD httpfs")
    return connection


def iter_liquidation_deltas(
    node: Any,
) -> Iterator[tuple[dict[str, Any], list[str], str | None, str | None]]:
    """Yield only explicit LedgerUpdate liquidation deltas."""
    if isinstance(node, list):
        for item in node:
            yield from iter_liquidation_deltas(item)
        return
    if not isinstance(node, dict):
        return

    def from_ledger(
        ledger: Any,
    ) -> Iterator[tuple[dict[str, Any], list[str], str | None, str | None]]:
        if not isinstance(ledger, dict):
            return
        delta = ledger.get("delta")
        users_raw = ledger.get("users", [])
        users = (
            [str(value).lower() for value in users_raw]
            if isinstance(users_raw, list)
            else []
        )
        if isinstance(delta, dict) and delta.get("type") == "liquidation":
            event_hash = node.get("hash")
            event_time = node.get("time")
            yield (
                delta,
                users,
                str(event_hash) if event_hash is not None else None,
                str(event_time) if event_time is not None else None,
            )

    yield from from_ledger(node.get("LedgerUpdate"))
    inner = node.get("inner")
    if isinstance(inner, dict):
        yield from from_ledger(inner.get("LedgerUpdate"))
    payload = node.get("payload")
    if payload is not None:
        yield from iter_liquidation_deltas(payload)


def validate_liquidation(
    delta: dict[str, Any],
    *,
    block_number: int,
    block_time: str,
    local_time: str,
    event_hash: str | None,
    event_time: str | None,
    users: list[str],
    source_path: str,
    event_ordinal: int,
    ledger_ordinal: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    liquidated_notional = parse_number(
        delta.get("liquidatedNtlPos"), "liquidatedNtlPos"
    )
    account_value = parse_number(delta.get("accountValue"), "accountValue")
    if liquidated_notional <= 0:
        raise ValueError("liquidatedNtlPos must be positive")
    leverage_type = delta.get("leverageType")
    if leverage_type not in {"Cross", "Isolated"}:
        raise ValueError(f"invalid leverageType {leverage_type!r}")
    positions_raw = delta.get("liquidatedPositions")
    if not isinstance(positions_raw, list) or not positions_raw:
        raise ValueError("liquidatedPositions must be nonempty")

    positions: list[dict[str, Any]] = []
    for position_index, item in enumerate(positions_raw):
        if not isinstance(item, dict):
            raise ValueError("liquidated position is not an object")
        coin = str(item.get("coin", "")).strip().upper()
        if not coin:
            raise ValueError("liquidated position coin is empty")
        signed_size = parse_number(item.get("szi"), "szi")
        if signed_size == 0:
            raise ValueError("liquidated position size is zero")
        positions.append(
            {
                "position_index": position_index,
                "coin": coin,
                "signed_size": signed_size,
                "forced_flow_side": "SELL" if signed_size > 0 else "BUY",
            }
        )

    identity = {
        "block_number": block_number,
        "event_hash": event_hash or "",
        "event_ordinal": event_ordinal,
        "ledger_ordinal": ledger_ordinal,
    }
    event = {
        "identity": identity,
        "source_path": source_path,
        "block_number": block_number,
        "block_time": block_time,
        "local_time": local_time,
        "event_hash": event_hash,
        "event_time": event_time,
        "users": users,
        "liquidated_notional": liquidated_notional,
        "account_value": account_value,
        "leverage_type": leverage_type,
        "positions": positions,
    }
    return event, positions


def parse_event_row(
    row: tuple[Any, Any, Any, Any, Any],
    row_ordinal: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    local_raw, block_raw, block_number_raw, events_raw, source_raw = row
    try:
        local_time = parse_timestamp(local_raw, "local_time")
        block_time = parse_timestamp(block_raw, "block_time")
        block_number = int(block_number_raw)
        source_path = str(source_raw)
        events = json.loads(events_raw) if isinstance(events_raw, str) else events_raw
        if not isinstance(events, list):
            raise ValueError("events payload is not a list")
    except Exception as exc:
        return [], [], {"row_ordinal": row_ordinal, "error": repr(exc)}

    liquidations: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []
    for event_ordinal, event_node in enumerate(events):
        ledger_ordinal = 0
        for delta, users, event_hash, event_time in iter_liquidation_deltas(
            event_node
        ):
            try:
                validated, _ = validate_liquidation(
                    delta,
                    block_number=block_number,
                    block_time=block_time,
                    local_time=local_time,
                    event_hash=event_hash,
                    event_time=event_time,
                    users=users,
                    source_path=source_path,
                    event_ordinal=event_ordinal,
                    ledger_ordinal=ledger_ordinal,
                )
                liquidations.append(validated)
            except Exception as exc:
                malformed.append(
                    {
                        "row_ordinal": row_ordinal,
                        "source_path": source_path,
                        "event_ordinal": event_ordinal,
                        "ledger_ordinal": ledger_ordinal,
                        "error": repr(exc),
                    }
                )
            ledger_ordinal += 1
    return liquidations, malformed, None


def query_source(
    revision: str,
    siblings: list[dict[str, Any]],
    paths: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    urls = [revision_url(revision, str(item["rfilename"])) for item in siblings]
    coverage_sql, event_sql = build_queries(urls, paths)
    connection = connect_duckdb()
    try:
        coverage_rows = connection.execute(coverage_sql).fetchall()
        coverage = [
            {
                "path": str(row[0]),
                "row_count": int(row[1]),
                "block_min": int(row[2]),
                "block_max": int(row[3]),
                "local_time_min": str(row[4]),
                "local_time_max": str(row[5]),
                "nonempty_event_rows": int(row[6]),
            }
            for row in coverage_rows
        ]

        cursor = connection.execute(event_sql)
        liquidations: list[dict[str, Any]] = []
        malformed_rows: list[dict[str, Any]] = []
        malformed_liquidations: list[dict[str, Any]] = []
        row_ordinal = 0
        while True:
            rows = cursor.fetchmany(10_000)
            if not rows:
                break
            for row in rows:
                found, malformed, row_error = parse_event_row(row, row_ordinal)
                liquidations.extend(found)
                malformed_liquidations.extend(malformed)
                if row_error is not None:
                    malformed_rows.append(row_error)
                row_ordinal += 1
    finally:
        connection.close()

    diagnostics = {
        "parquet_urls": urls,
        "coverage_sql_sha256": digest_bytes(coverage_sql.encode("utf-8")),
        "event_sql_sha256": digest_bytes(event_sql.encode("utf-8")),
        "event_rows_read": row_ordinal,
        "malformed_rows": malformed_rows,
        "malformed_liquidations": malformed_liquidations,
    }
    return coverage, liquidations, diagnostics


def run_gate(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    revision, metadata = resolve_revision(session)
    siblings = find_parquet_siblings(metadata)
    paths = candidate_paths()
    coverage, all_liquidations, diagnostics = query_source(
        revision, siblings, paths
    )

    identities = [
        (
            event["identity"]["block_number"],
            event["identity"]["event_hash"],
            event["identity"]["event_ordinal"],
            event["identity"]["ledger_ordinal"],
        )
        for event in all_liquidations
    ]
    duplicate_count = len(identities) - len(set(identities))

    coverage_by_path = {item["path"]: item for item in coverage}
    files_by_date: Counter[str] = Counter()
    liquidation_events_by_date: Counter[str] = Counter()
    target_position_count = 0
    target_coin_counts: Counter[str] = Counter()
    for path in paths:
        item = coverage_by_path.get(path)
        if item is not None and item["row_count"] > 0:
            date_token = path.split("/")[-2]
            date_text = f"{date_token[:4]}-{date_token[4:6]}-{date_token[6:8]}"
            files_by_date[date_text] += 1
    for event in all_liquidations:
        date_token = event["source_path"].split("/")[-2]
        date_text = f"{date_token[:4]}-{date_token[4:6]}-{date_token[6:8]}"
        liquidation_events_by_date[date_text] += 1
        for position in event["positions"]:
            coin = position["coin"]
            if coin in TARGET_COINS:
                target_position_count += 1
                target_coin_counts[coin] += 1

    parsed_count = len(coverage_by_path)
    malformed_row_count = len(diagnostics["malformed_rows"])
    malformed_liquidation_count = len(
        diagnostics["malformed_liquidations"]
    )
    nonzero_dates = sum(
        liquidation_events_by_date[date] > 0 for date in DATES
    )
    represented_target_coins = sum(
        target_coin_counts[coin] > 0 for coin in TARGET_COINS
    )

    checks = {
        "immutable_revision_resolved": bool(revision),
        "commit_pinned_parquet_sibling_found": bool(siblings),
        "no_2026_path": all("2026" not in path for path in paths),
        "minimum_files_33_of_36": parsed_count >= 33,
        "minimum_five_files_each_date": all(
            files_by_date[date] >= 5 for date in DATES
        ),
        "malformed_rows_zero": malformed_row_count == 0,
        "malformed_explicit_liquidations_zero": malformed_liquidation_count
        == 0,
        "duplicate_liquidation_identity_zero": duplicate_count == 0,
        "at_least_four_nonzero_dates": nonzero_dates >= 4,
        "at_least_20_explicit_liquidations": len(all_liquidations) >= 20,
        "at_least_two_target_coins": represented_target_coins >= 2,
        "at_least_10_target_position_records": target_position_count >= 10,
    }

    sibling_evidence = []
    for item in siblings:
        sibling_evidence.append(
            {
                "rfilename": item.get("rfilename"),
                "size": item.get("size"),
                "blob_id": item.get("blobId") or item.get("blob_id"),
                "lfs": item.get("lfs"),
                "url_sha256": digest_bytes(
                    revision_url(revision, str(item["rfilename"])).encode(
                        "utf-8"
                    )
                ),
            }
        )

    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-2058-ML-HL-LIQUIDATION-001",
        "phase": "OUTCOME_SEALED_SOURCE_GATE",
        "transport": "COMMIT_PINNED_CONSOLIDATED_PARQUET_PREDICATE_PUSHDOWN",
        "repository": REPOSITORY,
        "resolved_revision": revision,
        "metadata_sha256": digest_bytes(stable_json_bytes(metadata)),
        "parquet_siblings": sibling_evidence,
        "frozen_dates": list(DATES),
        "frozen_hours": list(HOURS),
        "requested_file_count": len(paths),
        "parsed_file_count": parsed_count,
        "files_by_date": {date: files_by_date[date] for date in DATES},
        "coverage": coverage,
        "nonempty_event_rows_read": diagnostics["event_rows_read"],
        "liquidation_events_by_date": {
            date: liquidation_events_by_date[date] for date in DATES
        },
        "explicit_liquidation_event_count": len(all_liquidations),
        "target_position_record_count": target_position_count,
        "target_coin_counts": {
            coin: target_coin_counts[coin] for coin in TARGET_COINS
        },
        "represented_target_coin_count": represented_target_coins,
        "duplicate_identity_count": duplicate_count,
        "malformed_row_count": malformed_row_count,
        "malformed_explicit_liquidation_count": malformed_liquidation_count,
        "coverage_sql_sha256": diagnostics["coverage_sql_sha256"],
        "event_sql_sha256": diagnostics["event_sql_sha256"],
        "checks": checks,
        "source_gate_pass": all(checks.values()),
        "scientific_decision": (
            "OPEN_FROZEN_HISTORICAL_MODEL_STAGE"
            if all(checks.values())
            else "CLOSE_SOURCE_ROUTE_BEFORE_MARKET_OUTCOMES"
        ),
        "market_price_opened": False,
        "future_return_opened": False,
        "model_fitted": False,
        "strategy_pnl_opened": False,
        "official_2026_opened": False,
        "orders_submitted": False,
    }

    write_json(output / "SOURCE_GATE_RESULT.json", result)
    write_json(output / "REPOSITORY_METADATA.json", metadata)
    write_json(
        output / "SOURCE_MANIFEST.json",
        {
            "schema_version": 1,
            "repository": REPOSITORY,
            "resolved_revision": revision,
            "metadata_sha256": result["metadata_sha256"],
            "parquet_siblings": sibling_evidence,
            "frozen_paths": paths,
            "coverage": coverage,
            "coverage_sql_sha256": diagnostics["coverage_sql_sha256"],
            "event_sql_sha256": diagnostics["event_sql_sha256"],
        },
    )
    write_json(
        output / "PARSE_ERRORS.json",
        {
            "malformed_rows": diagnostics["malformed_rows"],
            "malformed_liquidations": diagnostics[
                "malformed_liquidations"
            ],
        },
    )
    with gzip.open(
        output / "LIQUIDATIONS.jsonl.gz", "wt", encoding="utf-8"
    ) as handle:
        for event in sorted(
            all_liquidations,
            key=lambda row: (
                row["local_time"],
                row["block_number"],
                row["identity"]["event_ordinal"],
                row["identity"]["ledger_ordinal"],
            ),
        ):
            handle.write(
                json.dumps(event, sort_keys=True, ensure_ascii=False)
            )
            handle.write("\n")
    return result


def self_test() -> None:
    assert len(candidate_paths()) == 36
    assert all("2026" not in path for path in candidate_paths())
    metadata = {
        "siblings": [
            {"rfilename": ".gitattributes"},
            {"rfilename": "data/example.parquet", "size": 123},
        ]
    }
    assert find_parquet_siblings(metadata)[0]["rfilename"] == "data/example.parquet"
    coverage_sql, event_sql = build_queries(
        ["https://example.invalid/data.parquet"], candidate_paths()
    )
    assert "GROUP BY _src" in coverage_sql
    assert "trim(events) <> '[]'" in event_sql

    synthetic = {
        "time": "2025-10-06T00:00:00.100000000",
        "hash": "0xabc",
        "inner": {
            "LedgerUpdate": {
                "users": ["0xUSER"],
                "delta": {
                    "type": "liquidation",
                    "liquidatedNtlPos": "1000.5",
                    "accountValue": "-12.0",
                    "leverageType": "Cross",
                    "liquidatedPositions": [
                        {"coin": "ETH", "szi": "1.25"},
                        {"coin": "BTC", "szi": "-0.01"},
                    ],
                },
            }
        },
    }
    found = list(iter_liquidation_deltas(synthetic))
    assert len(found) == 1
    delta, users, event_hash, event_time = found[0]
    event, positions = validate_liquidation(
        delta,
        block_number=123,
        block_time="2025-10-06T00:00:00.100000",
        local_time="2025-10-06T00:00:00.250000",
        event_hash=event_hash,
        event_time=event_time,
        users=users,
        source_path="synthetic",
        event_ordinal=0,
        ledger_ordinal=0,
    )
    assert event["account_value"] == -12.0
    assert positions[0]["forced_flow_side"] == "SELL"
    assert positions[1]["forced_flow_side"] == "BUY"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("SELF_TEST_PASS")
        return 0
    if args.output is None:
        parser.error("--output is required unless --self-test is used")
    try:
        result = run_gate(args.output)
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        result = {
            "schema_version": 1,
            "claim_id": "CLM-20260726-2058-ML-HL-LIQUIDATION-001",
            "phase": "OUTCOME_SEALED_SOURCE_GATE",
            "transport": "COMMIT_PINNED_CONSOLIDATED_PARQUET_PREDICATE_PUSHDOWN",
            "source_gate_pass": False,
            "scientific_decision": "CLOSE_SOURCE_ROUTE_BEFORE_MARKET_OUTCOMES",
            "fatal_error": repr(exc),
            "market_price_opened": False,
            "future_return_opened": False,
            "model_fitted": False,
            "strategy_pnl_opened": False,
            "official_2026_opened": False,
            "orders_submitted": False,
        }
        write_json(args.output / "SOURCE_GATE_RESULT.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
