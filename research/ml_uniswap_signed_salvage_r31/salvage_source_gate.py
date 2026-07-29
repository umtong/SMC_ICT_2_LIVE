from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests

import probe_uniswap_swaps as base

BLOCKSCOUT_RPC = "https://eth.blockscout.com/api/eth-rpc"
BLOCKSCOUT_V2 = "https://eth.blockscout.com/api/v2"
MIN_INTERVAL = 0.55
MISSING_WINDOW = ("2023-08-17", 12)


class PacedTransport:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SMC-ICT-2-Uniswap-salvage/1.0"})
        self.last = 0.0
        self.counter = 0
        self.calls = 0
        self.retries = 0

    def pace(self) -> None:
        delay = MIN_INTERVAL - (time.monotonic() - self.last)
        if delay > 0:
            time.sleep(delay)

    def get_json(self, url: str, attempts: int = 8) -> Any:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                self.pace()
                response = self.session.get(url, timeout=(15, 90))
                self.last = time.monotonic()
                self.calls += 1
                if response.status_code == 429 or response.status_code >= 500:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last = exc
                if attempt + 1 >= attempts:
                    break
                self.retries += 1
                time.sleep(min(30.0, 2.0 * (2**attempt)))
        raise RuntimeError(f"GET failed: {url}: {last!r}")

    def rpc(self, method: str, params: list[Any], attempts: int = 8) -> Any:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                self.counter += 1
                payload = {
                    "jsonrpc": "2.0",
                    "id": self.counter,
                    "method": method,
                    "params": params,
                }
                self.pace()
                response = self.session.post(BLOCKSCOUT_RPC, json=payload, timeout=(15, 90))
                self.last = time.monotonic()
                self.calls += 1
                if response.status_code == 429 or response.status_code >= 500:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
                response.raise_for_status()
                body = response.json()
                if body.get("error") is not None:
                    raise RuntimeError(json.dumps(body["error"], sort_keys=True))
                return body["result"]
            except Exception as exc:
                last = exc
                if attempt + 1 >= attempts:
                    break
                self.retries += 1
                time.sleep(min(30.0, 2.0 * (2**attempt)))
        raise RuntimeError(f"RPC {method} failed: {last!r}")

    def block_timestamp(self, block: int, cache: dict[int, int]) -> int:
        block = int(block)
        if block not in cache:
            body = self.get_json(f"{BLOCKSCOUT_V2}/blocks/{block}")
            if int(body["height"]) != block:
                raise RuntimeError(f"block identity mismatch {block}")
            stamp = dt.datetime.fromisoformat(str(body["timestamp"]).replace("Z", "+00:00"))
            cache[block] = int(stamp.timestamp())
        return cache[block]

    def first_at_or_after(self, target: int, cache: dict[int, int]) -> int:
        latest = int(str(self.rpc("eth_blockNumber", [])), 16)
        low, high = 0, latest
        while low < high:
            mid = (low + high) // 2
            if self.block_timestamp(mid, cache) < target:
                low = mid + 1
            else:
                high = mid
        # The final lower bound can be produced by ``mid + 1`` without ever
        # having been fetched. Cache it explicitly before later assertions.
        self.block_timestamp(low, cache)
        return low

    def logs_adaptive(
        self,
        *,
        address: str,
        from_block: int,
        to_block: int,
        topic0: str,
        depth: int = 0,
    ) -> list[dict[str, Any]]:
        if depth > 32:
            raise RuntimeError("eth_getLogs bisection depth exceeded")
        try:
            result = self.rpc(
                "eth_getLogs",
                [{
                    "fromBlock": hex(int(from_block)),
                    "toBlock": hex(int(to_block)),
                    "address": base.normalize_address(address),
                    "topics": [topic0],
                }],
            )
            if not isinstance(result, list):
                raise RuntimeError("eth_getLogs did not return a list")
            return result
        except Exception as exc:
            text = str(exc).lower()
            range_markers = (
                "-32005",
                "too many",
                "more than",
                "response size",
                "range too large",
                "limit exceeded",
                "block range",
            )
            if not any(marker in text for marker in range_markers):
                raise
            if int(from_block) >= int(to_block):
                raise RuntimeError(
                    f"single-block eth_getLogs failed at {from_block}: {exc!r}"
                ) from exc
            midpoint = (int(from_block) + int(to_block)) // 2
            return self.logs_adaptive(
                address=address,
                from_block=from_block,
                to_block=midpoint,
                topic0=topic0,
                depth=depth + 1,
            ) + self.logs_adaptive(
                address=address,
                from_block=midpoint + 1,
                to_block=to_block,
                topic0=topic0,
                depth=depth + 1,
            )


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl_gz(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    prior = json.loads((args.prior / "PROBE_RESULT.json").read_text())
    if prior.get("claim_id") != base.CLAIM_ID:
        raise RuntimeError("claim mismatch")
    records = load_jsonl_gz(args.prior / "RAW_SWAP_LOGS.jsonl.gz")
    pools = prior["resolved_pools"]
    transport = PacedTransport()
    timestamp_cache: dict[int, int] = {
        int(row["block_number"]): int(row["block_timestamp"]) for row in records
    }

    # Recover every transport-only decode error from the retained raw log.
    recovered: list[dict[str, Any]] = []
    for item in prior.get("decode_errors", []):
        raw = item["raw_log"]
        block = base.hex_int(raw["blockNumber"])
        stamp = transport.block_timestamp(block, timestamp_cache)
        pool_name = item["pool_name"]
        info = pools[pool_name]
        row = base.decode_swap_log(
            raw,
            pool_name=pool_name,
            expected_pool=info["pool"],
            token0=info["token0"],
            token1=info["token1"],
            fee=info["fee"],
            block_timestamp=stamp,
        )
        row["probe_window"] = item["probe_window"]
        recovered.append(row)
    records.extend(recovered)

    # Query only the one window never completed by the prior immutable run.
    date_text, hour = MISSING_WINDOW
    start_ts, end_ts = base.one_hour_window(date_text, hour)
    start_block = transport.first_at_or_after(start_ts, timestamp_cache)
    end_block = transport.first_at_or_after(end_ts, timestamp_cache) - 1
    window_key = f"{date_text}T{hour:02d}:00:00Z"
    new_records: list[dict[str, Any]] = []
    for pool_name, info in pools.items():
        if info["status"] != "PASS":
            continue
        logs = transport.logs_adaptive(
            address=info["pool"],
            from_block=start_block,
            to_block=end_block,
            topic0=base.SWAP_TOPIC,
        )
        blocks = sorted({base.hex_int(raw["blockNumber"]) for raw in logs})
        for block in blocks:
            transport.block_timestamp(block, timestamp_cache)
        for raw in logs:
            block = base.hex_int(raw["blockNumber"])
            row = base.decode_swap_log(
                raw,
                pool_name=pool_name,
                expected_pool=info["pool"],
                token0=info["token0"],
                token1=info["token1"],
                fee=info["fee"],
                block_timestamp=timestamp_cache[block],
            )
            row["probe_window"] = window_key
            new_records.append(row)
    records.extend(new_records)

    identity = [(r["block_hash"], r["transaction_hash"], r["log_index"]) for r in records]
    if len(identity) != len(set(identity)):
        raise RuntimeError("duplicate log identity after salvage")
    records.sort(key=lambda r: (r["block_number"], r["transaction_index"], r["log_index"]))

    result = dict(prior)
    result.pop("fatal_error", None)
    result["decode_errors"] = []
    result["window_ranges"] = dict(prior.get("window_ranges", {}))
    start_stamp = transport.block_timestamp(start_block, timestamp_cache)
    end_stamp = transport.block_timestamp(end_block, timestamp_cache)
    result["window_ranges"][window_key] = {
        "from_block": start_block,
        "to_block": end_block,
        "from_block_time": dt.datetime.fromtimestamp(
            start_stamp, tz=dt.timezone.utc
        ).isoformat(),
        "to_block_time": dt.datetime.fromtimestamp(
            end_stamp, tz=dt.timezone.utc
        ).isoformat(),
    }
    summaries: dict[str, Any] = {}
    for date, hour_value in base.PROBE_WINDOWS:
        key = f"{date}T{hour_value:02d}:00:00Z"
        summaries[key] = base.summarize([r for r in records if r["probe_window"] == key])
    result["window_summaries"] = summaries
    result["transport_correction"] = {
        "source_prior_sha256": file_sha(args.prior / "PROBE_RESULT.json"),
        "recovered_prior_decode_errors": len(recovered),
        "queried_only_missing_window": window_key,
        "block_timestamp_transport": "Blockscout v2 GET /blocks/{height}",
        "rpc_transport": BLOCKSCOUT_RPC,
        "http_calls": transport.calls,
        "retries": transport.retries,
    }
    checks = base.evaluate_gate(result, records)
    result["source_gate_checks"] = checks
    result["source_gate_pass"] = all(checks.values())
    result["scientific_decision"] = (
        "OPEN_FROZEN_PRE2024_HISTORY_AND_MODEL_STAGE"
        if result["source_gate_pass"]
        else "CLOSE_SOURCE_ROUTE_BEFORE_OUTCOMES"
    )
    result["totals"] = {
        "decoded_logs": len(records),
        "unique_transactions": len({r["transaction_hash"] for r in records}),
        "unique_blocks": len({r["block_number"] for r in records}),
        "decode_error_count": 0,
        "transport_http_calls": transport.calls,
        "transport_retries": transport.retries,
    }
    result["market_outcome_opened"] = False
    result["model_fit"] = False
    result["trade_or_pnl_opened"] = False
    result["official_2024_2026_opened"] = False

    raw_path = args.output / "RAW_SWAP_LOGS.jsonl.gz"
    with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    result_path = args.output / "PROBE_RESULT.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    manifest = {
        result_path.name: file_sha(result_path),
        raw_path.name: file_sha(raw_path),
    }
    (args.output / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "source_gate_pass": result["source_gate_pass"],
                "checks": checks,
                "totals": result["totals"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["source_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
