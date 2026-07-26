from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Iterable

import source_gate_blockscout as source
import source_gate_blockscout_authoritative as authority

RPC_ENDPOINT = "https://eth.blockscout.com/api/eth-rpc"
BATCH_SIZE = 40
REQUEST_INTERVAL_SECONDS = 0.40
BaseClient = source.BlockscoutClient
CORRECTION_FILE = Path(__file__).with_name(
    "CORRECTION_019_BLOCKSCOUT_STATUS0_FAIL_CLOSED_BEFORE_OUTCOME.json"
)
CORRECTION_ID = (
    "CORRECTION-20260727-ML-STABLECOIN-BLOCKSCOUT-STATUS0-FAIL-CLOSED-019"
)

_EXPLICIT_NO_RECORD_MARKERS = (
    "no records found",
    "no logs found",
    "no matching records found",
    "no data found",
    "no transactions found",
)
_EXPLICIT_RANGE_LIMIT_MARKERS = (
    "query timeout",
    "query timed out",
    "please select a smaller result dataset",
    "result window is too large",
    "block range is too wide",
    "response size exceeded",
    "too many results",
)


def _response_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def _response_haystack(body: dict[str, Any]) -> str:
    return " | ".join(
        (_response_text(body.get("message")), _response_text(body.get("result")))
    ).lower()


def is_explicit_no_records_response(body: dict[str, Any]) -> bool:
    text = _response_haystack(body)
    return any(marker in text for marker in _EXPLICIT_NO_RECORD_MARKERS)


def is_explicit_range_limit_response(body: dict[str, Any]) -> bool:
    text = _response_haystack(body)
    return any(marker in text for marker in _EXPLICIT_RANGE_LIMIT_MARKERS)


class ExactBatchClient(BaseClient):
    """Preserve the corrected source contract while batching exact block timestamps."""

    def logs(
        self,
        address: str,
        direction: str,
        start_block: int,
        end_block: int,
        diagnostics: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        body = self.get_json(
            source.API_BASE,
            self._log_params(address, direction, start_block, end_block),
        )
        if not isinstance(body, dict):
            raise source.BlockscoutError(
                f"getLogs response must be an object, got {type(body)!r}"
            )
        status = str(body.get("status"))
        result = body.get("result")
        provider_text = _response_haystack(body)

        if status == "0":
            if is_explicit_no_records_response(body):
                diagnostics.append(
                    {
                        "from_block": start_block,
                        "to_block": end_block,
                        "status": "PASS_EMPTY_EXPLICIT_NO_RECORDS",
                        "log_count": 0,
                        "provider_text": provider_text[:500],
                    }
                )
                return []

            if is_explicit_range_limit_response(body):
                if start_block >= end_block:
                    raise source.BlockscoutError(
                        "single block returned an explicit range-limit response: "
                        f"{body}"
                    )
                mid = (start_block + end_block) // 2
                diagnostics.append(
                    {
                        "from_block": start_block,
                        "to_block": end_block,
                        "status": "SPLIT_EXPLICIT_RANGE_LIMIT",
                        "log_count": None,
                        "provider_text": provider_text[:500],
                    }
                )
                return self.logs(
                    address, direction, start_block, mid, diagnostics
                ) + self.logs(address, direction, mid + 1, end_block, diagnostics)

            raise source.BlockscoutError(
                "unrecognized status=0 response; fail closed instead of treating it "
                f"as an empty source interval: {body}"
            )

        if status != "1" or not isinstance(result, list):
            raise source.BlockscoutError(f"unexpected getLogs response: {body}")

        diagnostics.append(
            {
                "from_block": start_block,
                "to_block": end_block,
                "status": "PASS",
                "log_count": len(result),
            }
        )
        if len(result) < source.MAX_LOGS:
            return result
        if start_block >= end_block:
            raise source.BlockscoutError(
                "single block reached the 1000-log truncation ceiling"
            )
        mid = (start_block + end_block) // 2
        diagnostics[-1]["status"] = "SPLIT_AT_LIMIT"
        return self.logs(
            address, direction, start_block, mid, diagnostics
        ) + self.logs(address, direction, mid + 1, end_block, diagnostics)

    def _post_batch(self, block_numbers: Iterable[int]) -> dict[int, int]:
        numbers = tuple(dict.fromkeys(int(value) for value in block_numbers))
        payload: list[dict[str, object]] = []
        id_to_block: dict[int, int] = {}
        for request_id, block_number in enumerate(numbers, start=1):
            id_to_block[request_id] = block_number
            payload.append(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "eth_getBlockByNumber",
                    "params": [hex(block_number), False],
                }
            )

        last: Exception | None = None
        for attempt in range(7):
            try:
                elapsed = time.monotonic() - self.last_request_at
                if elapsed < REQUEST_INTERVAL_SECONDS:
                    time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)
                response = self.session.post(
                    RPC_ENDPOINT,
                    json=payload,
                    timeout=(15, 120),
                )
                self.last_request_at = time.monotonic()
                self.request_count += 1
                if response.status_code == 429 or response.status_code >= 500:
                    raise source.BlockscoutError(
                        f"HTTP {response.status_code}: {response.text[:300]}"
                    )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, list):
                    raise source.BlockscoutError(
                        f"batch response must be list, got {type(body)!r}"
                    )
                by_id = {
                    int(item["id"]): item
                    for item in body
                    if isinstance(item, dict) and "id" in item
                }
                result: dict[int, int] = {}
                for request_id, block_number in id_to_block.items():
                    item = by_id.get(request_id)
                    if item is None:
                        raise source.BlockscoutError(
                            f"missing batch response for block {block_number}"
                        )
                    if item.get("error") is not None:
                        raise source.BlockscoutError(
                            json.dumps(item["error"], sort_keys=True)
                        )
                    block = item.get("result")
                    if block is None:
                        raise source.BlockscoutError(
                            f"missing block result {block_number}"
                        )
                    result[block_number] = source.parse_int(block["timestamp"])
                return result
            except Exception as exc:
                last = exc
                self.errors.append(
                    f"{RPC_ENDPOINT}: {type(exc).__name__}: {exc}"
                )
                if attempt + 1 < 7:
                    time.sleep(min(30.0, 1.5 * (2**attempt)))
        raise source.BlockscoutError(
            f"exact block timestamp batch failed: {last!r}"
        )

    def block_timestamp(self, block_number: int) -> int:
        number = int(block_number)
        cached = self.block_timestamp_cache.get(number)
        if cached is not None:
            return cached
        start = max(0, number - 8)
        candidates = range(start, start + BATCH_SIZE)
        try:
            self.block_timestamp_cache.update(self._post_batch(candidates))
        except Exception:
            # Exact REST fallback; no approximation or interpolation is allowed.
            return super().block_timestamp(number)
        if number not in self.block_timestamp_cache:
            raise source.BlockscoutError(
                f"batch did not contain requested block {number}"
            )
        return self.block_timestamp_cache[number]


def _load_correction() -> dict[str, Any]:
    correction = json.loads(CORRECTION_FILE.read_text(encoding="utf-8"))
    if correction.get("correction_id") != CORRECTION_ID:
        raise AssertionError("transport response correction identity changed")
    if correction.get("recorded_before_source_decision_or_market_outcome") is not True:
        raise AssertionError("transport correction was not frozen before outcome")
    return correction


def bind_transport_response_policy(
    output: Path, result: dict[str, Any]
) -> dict[str, Any]:
    _load_correction()
    binding = {
        "transport_response_policy_correction": CORRECTION_ID,
        "status_zero_empty_policy": "EXPLICIT_NO_RECORDS_ONLY",
        "status_zero_range_policy": "EXPLICIT_RANGE_LIMIT_ONLY",
        "unrecognized_status_zero_policy": "FAIL_CLOSED_SOURCE_UNAVAILABLE",
    }
    result.update(binding)
    result_path = output / "SOURCE_GATE_RESULT.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path = output / "SOURCE_MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(binding)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return result


def self_test() -> None:
    _load_correction()

    client = object.__new__(ExactBatchClient)
    client.block_timestamp_cache = {}
    client.request_count = 0
    client.errors = []
    observed: list[tuple[int, ...]] = []

    def fake_batch(blocks: Iterable[int]) -> dict[int, int]:
        values = tuple(int(value) for value in blocks)
        observed.append(values)
        return {value: value * 12 for value in values}

    client._post_batch = fake_batch  # type: ignore[method-assign]
    assert client.block_timestamp(100) == 1200
    assert client.block_timestamp(101) == 1212
    assert len(observed) == 1
    assert observed[0][0] == 92 and observed[0][-1] == 131

    decoded = authority.base.decode_log(
        "USDT",
        "MINT",
        {
            "address": authority.base.CONTRACTS["USDT"]["address"],
            "topics": [authority.base.ISSUE_TOPIC, None, "", "0x"],
            "data": hex(1_000_000 * 10**6),
            "blockNumber": "0x10",
            "transactionHash": "0x" + "ab" * 32,
            "logIndex": "0x0",
        },
    )
    assert decoded["amount_usd"] == 1_000_000

    class FakeLogsClient(ExactBatchClient):
        def __init__(self, bodies: list[dict[str, Any]]) -> None:
            self._bodies = iter(bodies)

        def get_json(self, *_args: Any, **_kwargs: Any) -> Any:
            return next(self._bodies)

    address = authority.base.CONTRACTS["USDT"]["address"]
    empty_diagnostics: list[dict[str, Any]] = []
    assert (
        FakeLogsClient(
            [{"status": "0", "message": "No logs found", "result": []}]
        ).logs(address, "MINT", 10, 20, empty_diagnostics)
        == []
    )
    assert empty_diagnostics[0]["status"] == "PASS_EMPTY_EXPLICIT_NO_RECORDS"

    notok_body = {"status": "0", "message": "NOTOK", "result": []}
    assert not is_explicit_no_records_response(notok_body)
    try:
        FakeLogsClient([notok_body]).logs(address, "MINT", 10, 20, [])
    except source.BlockscoutError:
        pass
    else:
        raise AssertionError("NOTOK with an empty list was accepted as no records")

    rate_body = {
        "status": "0",
        "message": "NOTOK",
        "result": "Max rate limit reached",
    }
    assert not is_explicit_no_records_response(rate_body)
    assert not is_explicit_range_limit_response(rate_body)
    try:
        FakeLogsClient([rate_body]).logs(address, "MINT", 10, 20, [])
    except source.BlockscoutError:
        pass
    else:
        raise AssertionError("rate limiting was accepted as an empty interval")

    split_diagnostics: list[dict[str, Any]] = []
    rows = FakeLogsClient(
        [
            {
                "status": "0",
                "message": "NOTOK",
                "result": "Query Timeout occured. Please select a smaller result dataset",
            },
            {"status": "1", "message": "OK", "result": [{"id": "left"}]},
            {"status": "0", "message": "No records found", "result": []},
        ]
    ).logs(address, "MINT", 10, 11, split_diagnostics)
    assert rows == [{"id": "left"}]
    assert split_diagnostics[0]["status"] == "SPLIT_EXPLICIT_RANGE_LIMIT"

    print("pinned exact-batch fail-closed source self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    self_test()
    if args.self_test:
        return 0
    if args.output is None:
        raise SystemExit("--output is required")
    source.BlockscoutClient = ExactBatchClient
    result = source.source_gate(args.output)
    result = bind_transport_response_policy(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
