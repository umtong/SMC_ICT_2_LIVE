from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import time
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import requests

import probe_gmx_v1_liquidations_semantic as semantic

base = semantic.base

TAKEOVER_CLAIM_ID = "CLM-20260730-GMX-V1-LIQUIDATION-TAKEOVER-001"
PORTAL_ROOT = "https://portal.sqd.dev/datasets/arbitrum-one"
MAX_BLOCK_SPAN = 100_000


class PortalError(RuntimeError):
    pass


def parse_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer field")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("0x", "0X")):
            return int(text, 16)
        return int(text)
    raise ValueError(f"cannot parse integer {value!r}")


def parse_timestamp(value: Any) -> int:
    if isinstance(value, str) and not value.strip().startswith(("0x", "0X")):
        text = value.strip()
        if any(marker in text for marker in ("T", "-", ":")):
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
            return int(parsed.timestamp())
    number = parse_int(value)
    while number > 10_000_000_000:
        number //= 1000
    return number


def canonical_hex(value: Any) -> str:
    return hex(parse_int(value))


def normalize_hex_data(value: Any) -> str:
    text = str(value)
    return text if text.startswith("0x") else "0x" + text


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_gzip(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="\n") as text:
                for row in rows:
                    text.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


class PortalClient:
    def __init__(self, root: str = PORTAL_ROOT) -> None:
        self.root = root.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/x-ndjson, application/json",
                "Accept-Encoding": "gzip",
                "User-Agent": "SMC-ICT-2-GMX-V1-SQD-source-gate/1.0",
            }
        )
        self.last_request = 0.0
        self.stats = {"timestamp_calls": 0, "stream_calls": 0, "retries": 0, "errors": 0}

    def request(self, method: str, url: str, *, attempts: int = 6, **kwargs: Any) -> requests.Response:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                delay = 0.25 - (time.monotonic() - self.last_request)
                if delay > 0:
                    time.sleep(delay)
                response = self.session.request(method, url, timeout=(15, 180), **kwargs)
                self.last_request = time.monotonic()
                if response.status_code in {408, 425, 429} or response.status_code >= 500:
                    raise PortalError(f"retryable HTTP {response.status_code}: {response.text[:200]}")
                return response
            except Exception as exc:
                last = exc
                self.stats["errors"] += 1
                if attempt + 1 >= attempts:
                    break
                self.stats["retries"] += 1
                time.sleep(min(30.0, 1.5 * 2**attempt))
        raise PortalError(f"Portal request failed {method} {url}: {last!r}")

    def resolve_timestamp(self, timestamp: int) -> int:
        self.stats["timestamp_calls"] += 1
        response = self.request("GET", f"{self.root}/timestamps/{int(timestamp)}/block")
        response.raise_for_status()
        try:
            body: Any = response.json()
        except Exception:
            body = response.text.strip()

        def find_block(value: Any) -> int | None:
            if isinstance(value, Mapping):
                for key in ("block", "height", "number"):
                    if key in value:
                        try:
                            return parse_int(value[key])
                        except Exception:
                            pass
                for nested in value.values():
                    found = find_block(nested)
                    if found is not None:
                        return found
            elif isinstance(value, list):
                for nested in value:
                    found = find_block(nested)
                    if found is not None:
                        return found
            else:
                try:
                    return parse_int(value)
                except Exception:
                    return None
            return None

        block = find_block(body)
        if block is None:
            raise PortalError(f"timestamp endpoint returned no block: {body!r}")
        return block

    def stream(self, *, from_block: int, to_block: int) -> Iterator[dict[str, Any]]:
        cursor = int(from_block)
        last_global = cursor - 1
        while cursor <= int(to_block):
            chunk_end = min(int(to_block), cursor + MAX_BLOCK_SPAN - 1)
            payload = {
                "type": "evm",
                "fromBlock": cursor,
                "toBlock": chunk_end,
                "includeAllBlocks": False,
                "fields": {
                    "block": {"number": True, "hash": True, "timestamp": True},
                    "log": {
                        "address": True,
                        "topics": True,
                        "data": True,
                        "transactionHash": True,
                        "transactionIndex": True,
                        "logIndex": True,
                    },
                },
                "logs": [
                    {
                        "address": [base.normalize_address(base.VAULT)],
                        "topic0": [base.LIQUIDATE_POSITION_TOPIC.lower()],
                    }
                ],
            }
            self.stats["stream_calls"] += 1
            response = self.request(
                "POST", f"{self.root}/finalized-stream", json=payload, stream=True
            )
            if response.status_code == 204:
                cursor = chunk_end + 1
                continue
            response.raise_for_status()
            last_chunk: int | None = None
            for raw in response.iter_lines(decode_unicode=True):
                if not raw or not raw.strip():
                    continue
                parsed = json.loads(raw)
                rows = parsed if isinstance(parsed, list) else [parsed]
                for row in rows:
                    if not isinstance(row, Mapping):
                        raise PortalError(f"Portal row is not object: {row!r}")
                    header = row.get("header")
                    if not isinstance(header, Mapping):
                        raise PortalError(f"Portal row missing header: {row!r}")
                    number = parse_int(header.get("number"))
                    if number < cursor or number > chunk_end or number <= last_global:
                        raise PortalError(f"nonmonotone/out-of-range block {number}")
                    last_global = number
                    last_chunk = number
                    yield dict(row)
            cursor = chunk_end + 1 if last_chunk is None or last_chunk >= chunk_end else last_chunk + 1


def portal_log_to_rpc(header: Mapping[str, Any], log: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    block_number = parse_int(header.get("number"))
    block_timestamp = parse_timestamp(header.get("timestamp"))
    converted = {
        "address": base.normalize_address(str(log["address"])),
        "topics": [normalize_hex_data(value).lower() for value in log["topics"]],
        "data": normalize_hex_data(log["data"]),
        "blockNumber": hex(block_number),
        "blockHash": normalize_hex_data(header["hash"]).lower(),
        "transactionHash": normalize_hex_data(log["transactionHash"]).lower(),
        "transactionIndex": canonical_hex(log.get("transactionIndex", 0)),
        "logIndex": canonical_hex(log["logIndex"]),
        "removed": False,
    }
    return converted, block_timestamp


def self_test() -> None:
    assert parse_timestamp("2023-01-01T00:00:00Z") == 1672531200
    assert parse_timestamp(1672531200000) == 1672531200
    header = {"number": 10, "hash": "11" * 32, "timestamp": 1672531200}
    log = {
        "address": base.VAULT,
        "topics": [base.LIQUIDATE_POSITION_TOPIC],
        "data": "00",
        "transactionHash": "22" * 32,
        "transactionIndex": 1,
        "logIndex": 2,
    }
    converted, timestamp = portal_log_to_rpc(header, log)
    assert converted["blockNumber"] == "0xa" and timestamp == 1672531200
    assert converted["topics"][0] == base.LIQUIDATE_POSITION_TOPIC.lower()
    print("GMX_V1_SQD_SOURCE_GATE_SELF_TEST_PASS")


def run(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    client = PortalClient()
    result: dict[str, Any] = {
        "schema_version": 1,
        "takeover_claim_id": TAKEOVER_CLAIM_ID,
        "parent_claim_id": base.CLAIM_ID,
        "transport": "SQD_FINALIZED_PORTAL",
        "portal_root": PORTAL_ROOT,
        "chain_id": base.CHAIN_ID,
        "vault": base.VAULT,
        "event_topic0": base.LIQUIDATE_POSITION_TOPIC,
        "information_delay_seconds": base.INFORMATION_DELAY_SECONDS,
        "probe_windows": {},
        "decode_errors": [],
        "market_outcomes_opened": False,
        "orders_submitted": False,
    }
    rows: list[dict[str, Any]] = []
    try:
        for window in base.PROBE_WINDOWS:
            start = base.parse_utc(window["start"])
            end = base.parse_utc(window["end"])
            from_block = client.resolve_timestamp(start)
            to_block = max(from_block, client.resolve_timestamp(end) - 1)
            decoded: list[dict[str, Any]] = []
            raw_logs = 0
            for portal_row in client.stream(from_block=from_block, to_block=to_block):
                header = portal_row["header"]
                for portal_log in portal_row.get("logs", []):
                    raw_logs += 1
                    try:
                        rpc_log, block_timestamp = portal_log_to_rpc(header, portal_log)
                        decoded_row = semantic.decode_liquidation_log(
                            rpc_log,
                            block_timestamp=block_timestamp,
                            probe_window=window["name"],
                        )
                        if decoded_row["asset"] in base.INDEX_TOKENS:
                            decoded.append(decoded_row)
                    except Exception as exc:
                        result["decode_errors"].append(
                            {
                                "window": window["name"],
                                "block": header.get("number"),
                                "transactionHash": portal_log.get("transactionHash"),
                                "logIndex": portal_log.get("logIndex"),
                                "error": repr(exc),
                            }
                        )
            decoded.sort(
                key=lambda row: (
                    int(row["block_timestamp"]),
                    int(row["transaction_index"]),
                    int(row["log_index"]),
                )
            )
            rows.extend(decoded)
            result["probe_windows"][window["name"]] = {
                "from_block": from_block,
                "to_block": to_block,
                "raw_logs": raw_logs,
                "btc_eth_liquidations": len(decoded),
                "assets": sorted({row["asset"] for row in decoded}),
                "sides": sorted({row["liquidated_position_side"] for row in decoded}),
            }
            print(json.dumps({"window": window["name"], **result["probe_windows"][window["name"]]}, sort_keys=True), flush=True)
    except Exception as exc:
        result["source_error"] = repr(exc)

    rows.sort(
        key=lambda row: (
            int(row["block_timestamp"]),
            int(row["transaction_index"]),
            int(row["log_index"]),
        )
    )
    identities = [(row["block_hash"], row["transaction_hash"], int(row["log_index"])) for row in rows]
    nonempty = sum(int(value["btc_eth_liquidations"] > 0) for value in result["probe_windows"].values())
    assets = sorted({row["asset"] for row in rows})
    sides = sorted({row["liquidated_position_side"] for row in rows})
    checks = {
        "no_source_error": "source_error" not in result,
        "zero_decode_errors": len(result["decode_errors"]) == 0,
        "minimum_events": len(rows) >= 20,
        "minimum_nonempty_windows": nonempty >= 4,
        "both_assets": assets == ["BTC", "ETH"],
        "both_removed_sides": sides == ["LONG", "SHORT"],
        "unique_identities": len(identities) == len(set(identities)),
        "not_removed": all(not row.get("removed", False) for row in rows),
        "semantic_correction": all(
            row.get("external_market_order_direction_asserted") is False
            and row.get("source_censoring") == "LIQUIDATION_STATE_1_ONLY"
            and "forced_flow_direction" not in row
            for row in rows
        ),
    }
    result["portal_stats"] = client.stats
    result["totals"] = {
        "btc_eth_liquidations": len(rows),
        "unique_identities": len(set(identities)),
        "nonempty_windows": nonempty,
        "assets": assets,
        "sides": sides,
    }
    result["source_gate_checks"] = checks
    result["source_gate_pass"] = all(checks.values())
    result["scientific_decision"] = (
        "OPEN_FROZEN_PRE2024_HISTORY_AND_MODEL_STAGE"
        if result["source_gate_pass"]
        else (
            "SOURCE_UNAVAILABLE_NO_ALPHA_CONCLUSION"
            if "source_error" in result
            else "CLOSE_SOURCE_ROUTE_BEFORE_OUTCOMES"
        )
    )
    write_gzip(output / "RAW_GMX_V1_LIQUIDATIONS.jsonl.gz", rows)
    path = output / "SOURCE_GATE_RESULT.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "SOURCE_GATE_SHA256.txt").write_text(
        f"{sha256_file(path)}  {path.name}\n{sha256_file(output / 'RAW_GMX_V1_LIQUIDATIONS.jsonl.gz')}  RAW_GMX_V1_LIQUIDATIONS.jsonl.gz\n",
        encoding="utf-8",
    )
    print(json.dumps({"decision": result["scientific_decision"], **result["totals"]}, sort_keys=True))
    return 0 if result["source_gate_pass"] else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
        raise SystemExit(0)
    if arguments.output is None:
        raise SystemExit("--output is required")
    raise SystemExit(run(arguments.output))
