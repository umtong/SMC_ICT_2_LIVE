from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

import duckdb
import requests

import probe_uniswap_swaps as canonical

CLAIM_ID = "CLM-20260726-2110-ML-UNISWAP-HEDGE-TRANSFER-001"
TRANSPORT_ID = "TRANSPORT-20260726-UNISWAP-AWS-PUBLIC-PARQUET-001"
S3_BUCKET = "aws-public-blockchain"
S3_REGION = "us-east-2"
S3_ENDPOINT = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com"
S3_LIST_ENDPOINT = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/"
LOG_PREFIX = "v1.0/eth/logs/date={date}/"

# Factory-resolved Ethereum mainnet pools frozen by the parent claim.
POOL_METADATA: dict[str, dict[str, Any]] = {
    "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640": {
        "pool_name": "WETH_USDC_500",
        "token0": canonical.TOKENS["USDC"],
        "token1": canonical.TOKENS["WETH"],
        "fee": 500,
    },
    "0x8ad599c3a0ff1de082011efddc58f1908eb6e6d8": {
        "pool_name": "WETH_USDC_3000",
        "token0": canonical.TOKENS["USDC"],
        "token1": canonical.TOKENS["WETH"],
        "fee": 3000,
    },
    "0x11b815efb8f581194ae79006d24e0d814b7697f6": {
        "pool_name": "WETH_USDT_500",
        "token0": canonical.TOKENS["WETH"],
        "token1": canonical.TOKENS["USDT"],
        "fee": 500,
    },
    "0x4e68ccd3e89f51c3074ca5072bbac773960dfa36": {
        "pool_name": "WETH_USDT_3000",
        "token0": canonical.TOKENS["WETH"],
        "token1": canonical.TOKENS["USDT"],
        "fee": 3000,
    },
}

FIXED_WINDOWS = tuple(canonical.PROBE_WINDOWS)
FORBIDDEN_OUTCOME_FIELDS = (
    "future_return",
    "label",
    "action",
    "trade",
    "pnl",
    "model_metric",
    "official_2024_2026",
)


class TransportError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_s3_objects(prefix: str, timeout: int = 90) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers["User-Agent"] = "SMC-ICT-2-Uniswap-AWS-source-probe/1.0"
    token: str | None = None
    objects: list[dict[str, Any]] = []
    while True:
        params: dict[str, str] = {"list-type": "2", "prefix": prefix}
        if token:
            params["continuation-token"] = token
        response = session.get(S3_LIST_ENDPOINT, params=params, timeout=timeout)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        namespace = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
        for item in root.findall("s3:Contents", namespace):
            key = item.findtext("s3:Key", default="", namespaces=namespace)
            if not key.endswith(".parquet"):
                continue
            objects.append(
                {
                    "key": key,
                    "size": int(item.findtext("s3:Size", default="0", namespaces=namespace)),
                    "etag": item.findtext("s3:ETag", default="", namespaces=namespace).strip('"'),
                    "last_modified": item.findtext(
                        "s3:LastModified", default="", namespaces=namespace
                    ),
                }
            )
        if root.findtext("s3:IsTruncated", default="false", namespaces=namespace).lower() != "true":
            break
        token = root.findtext("s3:NextContinuationToken", namespaces=namespace)
        if not token:
            raise TransportError("truncated S3 listing without continuation token")
    objects.sort(key=lambda row: row["key"])
    return objects


def object_url(key: str) -> str:
    return f"{S3_ENDPOINT}/{urllib.parse.quote(key, safe='/=._-')}"


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def normalize_topic_list(value: Any) -> list[str]:
    if value is None:
        return []
    if hasattr(value, "as_py"):
        value = value.as_py()
    if not isinstance(value, (list, tuple)):
        raise TransportError(f"topics is not a list: {type(value)!r}")
    output: list[str] = []
    for item in value:
        if item is None:
            continue
        output.append(("0x" + item.hex() if isinstance(item, bytes) else str(item)).lower())
    return output


def normalize_hex(value: Any, *, expected_bytes: int | None = None) -> str:
    text = "0x" + value.hex() if isinstance(value, bytes) else str(value)
    if not text.startswith("0x"):
        text = "0x" + text
    text = text.lower()
    if expected_bytes is not None and len(text) != 2 + expected_bytes * 2:
        raise TransportError(
            f"hex width mismatch: expected {expected_bytes} bytes, got {len(text)} chars"
        )
    return text


def fetch_window(
    connection: duckdb.DuckDBPyConnection,
    *,
    urls: list[str],
    date_text: str,
    hour: int,
) -> list[dict[str, Any]]:
    if not urls:
        raise TransportError(f"no parquet objects for {date_text}")
    start = dt.datetime.fromisoformat(date_text).replace(
        hour=int(hour), minute=0, second=0, microsecond=0, tzinfo=dt.timezone.utc
    )
    end = start + dt.timedelta(hours=1)
    url_sql = "[" + ",".join(sql_string(url) for url in urls) + "]"
    address_sql = ",".join(sql_string(address) for address in sorted(POOL_METADATA))
    query = f"""
        SELECT lower(address) AS address, data, topics, block_timestamp,
               block_number, lower(block_hash) AS block_hash,
               lower(transaction_hash) AS transaction_hash,
               transaction_index, log_index
        FROM read_parquet({url_sql}, hive_partitioning=false, union_by_name=true)
        WHERE block_timestamp >= TIMESTAMP {sql_string(start.strftime('%Y-%m-%d %H:%M:%S'))}
          AND block_timestamp < TIMESTAMP {sql_string(end.strftime('%Y-%m-%d %H:%M:%S'))}
          AND lower(address) IN ({address_sql})
          AND lower(list_extract(topics, 1)) = {sql_string(canonical.SWAP_TOPIC.lower())}
        ORDER BY block_number, transaction_index, log_index
    """
    cursor = connection.execute(query)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def adapt_and_decode(row: dict[str, Any], window_key: str) -> dict[str, Any]:
    pool = str(row["address"]).lower()
    metadata = POOL_METADATA.get(pool)
    if metadata is None:
        raise TransportError(f"unexpected pool {pool}")
    raw_log = {
        "address": pool,
        "data": normalize_hex(row["data"]),
        "topics": normalize_topic_list(row["topics"]),
        "blockNumber": hex(int(row["block_number"])),
        "blockHash": normalize_hex(row["block_hash"], expected_bytes=32),
        "transactionHash": normalize_hex(row["transaction_hash"], expected_bytes=32),
        "transactionIndex": hex(int(row["transaction_index"])),
        "logIndex": hex(int(row["log_index"])),
        "removed": False,
    }
    timestamp_value = row["block_timestamp"]
    if isinstance(timestamp_value, dt.datetime):
        timestamp_value = (
            timestamp_value.replace(tzinfo=dt.timezone.utc)
            if timestamp_value.tzinfo is None
            else timestamp_value.astimezone(dt.timezone.utc)
        )
        block_timestamp = int(timestamp_value.timestamp())
    else:
        block_timestamp = int(timestamp_value)
    decoded = canonical.decode_swap_log(
        raw_log,
        pool_name=str(metadata["pool_name"]),
        expected_pool=pool,
        token0=str(metadata["token0"]),
        token1=str(metadata["token1"]),
        fee=int(metadata["fee"]),
        block_timestamp=block_timestamp,
    )
    decoded["probe_window"] = window_key
    decoded["transport"] = TRANSPORT_ID
    return decoded


def run_probe(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    dates = sorted({date_text for date_text, _ in FIXED_WINDOWS})
    inventories = {
        date_text: list_s3_objects(LOG_PREFIX.format(date=date_text))
        for date_text in dates
    }
    inventory_path = output / "OBJECT_INVENTORY.json"
    inventory_path.write_text(
        json.dumps(inventories, indent=2, sort_keys=True), encoding="utf-8"
    )

    decoded: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    connection = duckdb.connect(database=":memory:")
    connection.execute("INSTALL httpfs")
    connection.execute("LOAD httpfs")
    connection.execute(f"SET s3_region={sql_string(S3_REGION)}")
    try:
        for date_text, hour in FIXED_WINDOWS:
            window_key = f"{date_text}T{int(hour):02d}:00:00Z"
            objects = inventories[date_text]
            raw_rows: list[dict[str, Any]] = []
            try:
                raw_rows = fetch_window(
                    connection,
                    urls=[object_url(item["key"]) for item in objects],
                    date_text=date_text,
                    hour=int(hour),
                )
                for row in raw_rows:
                    try:
                        decoded.append(adapt_and_decode(row, window_key))
                    except Exception as exc:
                        errors.append(
                            {
                                "window": window_key,
                                "stage": "decode",
                                "error": repr(exc),
                                "block_number": row.get("block_number"),
                                "transaction_hash": row.get("transaction_hash"),
                                "log_index": row.get("log_index"),
                            }
                        )
            except Exception as exc:
                errors.append(
                    {"window": window_key, "stage": "scan", "error": repr(exc)}
                )
            window_rows = [row for row in decoded if row["probe_window"] == window_key]
            summaries[window_key] = {
                "object_count": len(objects),
                "object_bytes": sum(int(item["size"]) for item in objects),
                "raw_filtered_rows": len(raw_rows),
                "decoded_rows": len(window_rows),
                "unique_transactions": len({row["transaction_hash"] for row in window_rows}),
                "unique_blocks": len({row["block_number"] for row in window_rows}),
                "pool_counts": {
                    name: sum(row["pool_name"] == name for row in window_rows)
                    for name in sorted(
                        {str(item["pool_name"]) for item in POOL_METADATA.values()}
                    )
                },
            }
    finally:
        connection.close()

    decoded.sort(
        key=lambda row: (
            row["block_number"],
            row["transaction_index"],
            row["log_index"],
        )
    )
    identities = [
        (row["block_hash"], row["transaction_hash"], row["log_index"])
        for row in decoded
    ]
    checks = {
        "all_dates_have_parquet_objects": all(inventories[date] for date in dates),
        "all_six_windows_scanned": len(summaries) == len(FIXED_WINDOWS),
        "decode_errors_zero": len(errors) == 0,
        "duplicate_identity_zero": len(identities) == len(set(identities)),
        "at_least_four_dense_windows": sum(
            item["decoded_rows"] >= 10 for item in summaries.values()
        ) >= 4,
        "at_least_100_logs": len(decoded) >= 100,
        "timestamps_complete": all(
            isinstance(row.get("block_timestamp"), int) for row in decoded
        ),
    }
    transport_pass = all(checks.values())

    logs_path = output / "AWS_FILTERED_SWAP_LOGS.jsonl.gz"
    with gzip.open(logs_path, "wt", encoding="utf-8") as handle:
        for row in decoded:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")

    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "transport_id": TRANSPORT_ID,
        "phase": "OUTCOME_SEALED_TRANSPORT_PROBE",
        "provider": "AWS Public Blockchain Data Ethereum logs Parquet",
        "bucket": S3_BUCKET,
        "region": S3_REGION,
        "schema_source": "https://github.com/aws-solutions-library-samples/guidance-for-digital-assets-on-aws/blob/main/analytics/consumer/schema/eth.md",
        "fixed_windows": [
            {"date": date_text, "hour_utc": int(hour)}
            for date_text, hour in FIXED_WINDOWS
        ],
        "pools": POOL_METADATA,
        "swap_topic": canonical.SWAP_TOPIC,
        "window_summaries": summaries,
        "totals": {
            "decoded_logs": len(decoded),
            "unique_transactions": len({row["transaction_hash"] for row in decoded}),
            "unique_blocks": len({row["block_number"] for row in decoded}),
            "object_bytes_across_fixed_dates": sum(
                int(item["size"])
                for date_text in dates
                for item in inventories[date_text]
            ),
        },
        "errors": errors,
        "transport_checks": checks,
        "transport_pass": transport_pass,
        "scientific_decision": (
            "ELIGIBLE_FOR_CANONICAL_RPC_CROSSCHECK_BEFORE_FULL_HISTORY_USE"
            if transport_pass
            else "DO_NOT_USE_AWS_TRANSPORT"
        ),
        "crosscheck_required": (
            "Every fixed-window identity and decoded amount must match the canonical "
            "Uniswap/RPC source artifact before AWS may transport full 2021-2023 history."
        ),
        "forbidden_outcome_fields": list(FORBIDDEN_OUTCOME_FIELDS),
        "market_outcome_opened": False,
        "model_fit": False,
        "trade_or_pnl_opened": False,
        "official_2024_2026_opened": False,
        "credentials_used": False,
        "orders_submitted": False,
    }
    result_path = output / "AWS_TRANSPORT_PROBE_RESULT.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    (output / "SOURCE_MANIFEST.json").write_text(
        json.dumps(
            {
                inventory_path.name: sha256_file(inventory_path),
                logs_path.name: sha256_file(logs_path),
                result_path.name: sha256_file(result_path),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return result


def self_test() -> None:
    assert canonical.SWAP_TOPIC.lower().startswith("0xc42079")
    assert len(POOL_METADATA) == 4
    assert len(FIXED_WINDOWS) == 6
    assert object_url("v1.0/eth/logs/date=2021-05-19/a b.parquet").endswith(
        "v1.0/eth/logs/date=2021-05-19/a%20b.parquet"
    )
    assert normalize_hex(bytes.fromhex("ab"), expected_bytes=1) == "0xab"
    assert normalize_topic_list([canonical.SWAP_TOPIC])[0] == canonical.SWAP_TOPIC.lower()
    print("AWS public Parquet transport self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        raise SystemExit("--output is required")
    result = run_probe(args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
