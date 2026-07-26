from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import gzip
import hashlib
import json
import math
import tempfile
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import lz4.frame
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
USER_AGENT = "SMC-ICT-2-HL-liquidation-source-gate/1.0"


class SourceGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadResult:
    path: str
    status: str
    bytes: int
    sha256: str | None
    http_status: int | None
    error: str | None
    local_path: str | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
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
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is missing")
    text = value.strip()
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
    response = session.get(url, timeout=(20, 90))
    response.raise_for_status()
    metadata = response.json()
    revision = metadata.get("sha")
    if not isinstance(revision, str) or len(revision) < 12:
        raise SourceGateError(f"Unable to resolve immutable dataset SHA: {revision!r}")
    return revision, metadata


def download_one(
    revision: str,
    relative_path: str,
    directory: Path,
    *,
    attempts: int = 4,
) -> DownloadResult:
    safe_path = urllib.parse.quote(relative_path, safe="/")
    url = (
        f"https://huggingface.co/datasets/{REPOSITORY}/resolve/"
        f"{urllib.parse.quote(revision, safe='')}/{safe_path}?download=true"
    )
    target = directory / relative_path.replace("/", "__")
    last_error: str | None = None
    last_status: int | None = None
    for attempt in range(attempts):
        try:
            digest = hashlib.sha256()
            size = 0
            with requests.get(
                url,
                stream=True,
                timeout=(30, 300),
                headers={"User-Agent": USER_AGENT},
            ) as response:
                last_status = response.status_code
                if response.status_code == 404:
                    return DownloadResult(
                        relative_path, "MISSING", 0, None, 404, None, None
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    raise SourceGateError(
                        f"HTTP {response.status_code}: {response.text[:200]}"
                    )
                response.raise_for_status()
                with target.open("wb") as handle:
                    for chunk in response.iter_content(8 * 1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            if size <= 0:
                raise SourceGateError("downloaded zero bytes")
            return DownloadResult(
                relative_path,
                "DOWNLOADED",
                size,
                digest.hexdigest(),
                last_status,
                None,
                str(target),
            )
        except Exception as exc:
            last_error = repr(exc)
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass
            if attempt + 1 < attempts:
                time.sleep(min(8.0, 0.75 * (2**attempt)))
    return DownloadResult(
        relative_path, "ERROR", 0, None, last_status, last_error, None
    )


def iter_json_lines(path: Path) -> Iterator[tuple[int, Any]]:
    try:
        with lz4.frame.open(path, mode="rb") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                yield line_number, json.loads(raw)
    except RuntimeError:
        with path.open("rb") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                yield line_number, json.loads(raw)


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

    ledger = node.get("LedgerUpdate")
    if isinstance(ledger, dict):
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

    inner = node.get("inner")
    if isinstance(inner, dict):
        ledger = inner.get("LedgerUpdate")
        if isinstance(ledger, dict):
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


def parse_file(download: DownloadResult) -> dict[str, Any]:
    if download.status != "DOWNLOADED" or download.local_path is None:
        return {
            "path": download.path,
            "status": download.status,
            "bytes": download.bytes,
            "sha256": download.sha256,
            "http_status": download.http_status,
            "download_error": download.error,
            "rows": 0,
            "event_items": 0,
            "liquidations": [],
            "malformed_rows": [],
            "malformed_liquidations": [],
            "block_min": None,
            "block_max": None,
        }

    rows = 0
    event_items = 0
    block_min: int | None = None
    block_max: int | None = None
    liquidations: list[dict[str, Any]] = []
    malformed_rows: list[dict[str, Any]] = []
    malformed_liquidations: list[dict[str, Any]] = []

    try:
        for line_number, row in iter_json_lines(Path(download.local_path)):
            rows += 1
            try:
                if not isinstance(row, dict):
                    raise ValueError("row is not an object")
                block_number = int(row["block_number"])
                block_time = parse_timestamp(row["block_time"], "block_time")
                local_time = parse_timestamp(row["local_time"], "local_time")
                events = row.get("events")
                if not isinstance(events, list):
                    raise ValueError("events is not a list")
                block_min = (
                    block_number if block_min is None else min(block_min, block_number)
                )
                block_max = (
                    block_number if block_max is None else max(block_max, block_number)
                )
            except Exception as exc:
                malformed_rows.append(
                    {"line_number": line_number, "error": repr(exc)}
                )
                continue

            event_items += len(events)
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
                            source_path=download.path,
                            event_ordinal=event_ordinal,
                            ledger_ordinal=ledger_ordinal,
                        )
                        liquidations.append(validated)
                    except Exception as exc:
                        malformed_liquidations.append(
                            {
                                "line_number": line_number,
                                "event_ordinal": event_ordinal,
                                "ledger_ordinal": ledger_ordinal,
                                "error": repr(exc),
                            }
                        )
                    ledger_ordinal += 1
        status = "PARSED"
    except Exception as exc:
        status = "PARSE_ERROR"
        malformed_rows.append({"line_number": None, "error": repr(exc)})

    return {
        "path": download.path,
        "status": status,
        "bytes": download.bytes,
        "sha256": download.sha256,
        "http_status": download.http_status,
        "download_error": download.error,
        "rows": rows,
        "event_items": event_items,
        "liquidations": liquidations,
        "malformed_rows": malformed_rows,
        "malformed_liquidations": malformed_liquidations,
        "block_min": block_min,
        "block_max": block_max,
    }


def run_gate(output: Path, workers: int) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    revision, metadata = resolve_revision(session)
    metadata_bytes = json.dumps(
        metadata, sort_keys=True, separators=(",", ":")
    ).encode()
    paths = candidate_paths()

    with tempfile.TemporaryDirectory(prefix="hl-liquidation-source-") as temp_text:
        temp = Path(temp_text)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, workers)
        ) as pool:
            downloads = list(
                pool.map(lambda path: download_one(revision, path, temp), paths)
            )
        parsed = [parse_file(item) for item in downloads]

    all_liquidations = [
        event for file_result in parsed for event in file_result["liquidations"]
    ]
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

    files_by_date: Counter[str] = Counter()
    liquidation_events_by_date: Counter[str] = Counter()
    target_position_count = 0
    target_coin_counts: Counter[str] = Counter()
    for file_result in parsed:
        if file_result["status"] == "PARSED":
            date_token = file_result["path"].split("/")[-2]
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

    downloaded_count = sum(item.status == "DOWNLOADED" for item in downloads)
    parsed_count = sum(item["status"] == "PARSED" for item in parsed)
    malformed_row_count = sum(len(item["malformed_rows"]) for item in parsed)
    malformed_liquidation_count = sum(
        len(item["malformed_liquidations"]) for item in parsed
    )
    nonzero_dates = sum(
        liquidation_events_by_date[date] > 0 for date in DATES
    )
    represented_target_coins = sum(
        target_coin_counts[coin] > 0 for coin in TARGET_COINS
    )

    checks = {
        "immutable_revision_resolved": bool(revision),
        "no_2026_path": all("2026" not in path for path in paths),
        "minimum_files_33_of_36": parsed_count >= 33,
        "minimum_five_files_each_date": all(
            files_by_date[date] >= 5 for date in DATES
        ),
        "malformed_rows_zero": malformed_row_count == 0,
        "malformed_explicit_liquidations_zero": malformed_liquidation_count == 0,
        "duplicate_liquidation_identity_zero": duplicate_count == 0,
        "at_least_four_nonzero_dates": nonzero_dates >= 4,
        "at_least_20_explicit_liquidations": len(all_liquidations) >= 20,
        "at_least_two_target_coins": represented_target_coins >= 2,
        "at_least_10_target_position_records": target_position_count >= 10,
    }

    manifest_files = []
    for file_result in parsed:
        manifest_files.append(
            {
                key: value
                for key, value in file_result.items()
                if key
                not in {
                    "liquidations",
                    "malformed_rows",
                    "malformed_liquidations",
                }
            }
            | {
                "liquidation_count": len(file_result["liquidations"]),
                "malformed_row_count": len(file_result["malformed_rows"]),
                "malformed_liquidation_count": len(
                    file_result["malformed_liquidations"]
                ),
            }
        )

    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-2058-ML-HL-LIQUIDATION-001",
        "phase": "OUTCOME_SEALED_SOURCE_GATE",
        "repository": REPOSITORY,
        "resolved_revision": revision,
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "frozen_dates": list(DATES),
        "frozen_hours": list(HOURS),
        "requested_file_count": len(paths),
        "downloaded_file_count": downloaded_count,
        "parsed_file_count": parsed_count,
        "files_by_date": {date: files_by_date[date] for date in DATES},
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
            "files": manifest_files,
        },
    )
    write_json(
        output / "PARSE_ERRORS.json",
        {
            "malformed_rows": [
                {"path": item["path"], **error}
                for item in parsed
                for error in item["malformed_rows"]
            ],
            "malformed_liquidations": [
                {"path": item["path"], **error}
                for item in parsed
                for error in item["malformed_liquidations"]
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
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False))
            handle.write("\n")
    return result


def self_test() -> None:
    synthetic = {
        "local_time": "2025-10-06T00:00:00.250",
        "block_time": "2025-10-06T00:00:00.100",
        "block_number": 123,
        "events": [
            {
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
        ],
    }
    found = list(iter_liquidation_deltas(synthetic["events"][0]))
    assert len(found) == 1
    delta, users, event_hash, event_time = found[0]
    event, positions = validate_liquidation(
        delta,
        block_number=123,
        block_time=parse_timestamp(synthetic["block_time"], "block_time"),
        local_time=parse_timestamp(synthetic["local_time"], "local_time"),
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
    assert len(candidate_paths()) == 36


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("SELF_TEST_PASS")
        return 0
    if args.output is None:
        parser.error("--output is required unless --self-test is used")
    try:
        result = run_gate(args.output, args.workers)
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        result = {
            "schema_version": 1,
            "claim_id": "CLM-20260726-2058-ML-HL-LIQUIDATION-001",
            "phase": "OUTCOME_SEALED_SOURCE_GATE",
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
