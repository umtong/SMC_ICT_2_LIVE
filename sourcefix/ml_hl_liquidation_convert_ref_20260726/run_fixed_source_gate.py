from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_ROOT = REPO_ROOT / "research" / "ml_hl_liquidation_20260726"
sys.path.insert(0, str(ENGINE_ROOT))

import probe_hl_liquidations as engine  # noqa: E402

REVISION_REF = "refs/convert/parquet"
PARQUET_PATH = "default/train/0000.parquet"
FIX_ROOT = REPO_ROOT / "sourcefix" / "ml_hl_liquidation_convert_ref_20260726"
CORRECTION_004 = FIX_ROOT / "CORRECTION_004_CONVERT_PARQUET_REVISION_BEFORE_DATA.json"
CORRECTION_005 = FIX_ROOT / "CORRECTION_005_WRAPPER_SYMBOL_ALIGNMENT_BEFORE_DATA.json"
CORRECTION_006 = FIX_ROOT / "CORRECTION_006_LEDGER_LIQUIDATION_SCHEMA_BEFORE_DATA.json"


def stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_correction(path: Path) -> dict[str, Any]:
    correction = json.loads(path.read_text(encoding="utf-8"))
    assert correction["status"] == "PRE_OUTCOME_SOURCE_ONLY"
    assert correction["hyperliquid_event_row_opened_before_correction"] is False
    assert correction["market_outcome_opened_before_correction"] is False
    return correction


def resolve_convert_parquet_revision(_session: requests.Session) -> tuple[str, dict[str, object]]:
    corrections = [_load_correction(path) for path in (CORRECTION_004, CORRECTION_005, CORRECTION_006)]
    encoded_ref = quote(REVISION_REF, safe="")
    url = f"https://huggingface.co/api/datasets/{engine.REPOSITORY}/revision/{encoded_ref}"
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-hl-liquidation-convert-ref/3.0"
        response = session.get(url, params={"blobs": "true"}, timeout=120)
        response.raise_for_status()
        metadata = response.json()
    if not isinstance(metadata, dict):
        raise RuntimeError("convert/parquet revision metadata is not an object")
    resolved = str(metadata.get("sha") or "").strip()
    if len(resolved) < 12:
        raise RuntimeError("convert/parquet revision did not resolve to an immutable SHA")
    siblings = metadata.get("siblings")
    if not isinstance(siblings, list):
        raise RuntimeError("convert/parquet revision metadata has no sibling inventory")
    matching = [
        item
        for item in siblings
        if isinstance(item, dict) and str(item.get("rfilename")) == PARQUET_PATH
    ]
    if len(matching) != 1:
        raise RuntimeError(
            f"expected one {PARQUET_PATH} sibling in convert/parquet revision, found {len(matching)}"
        )
    raw = stable_json(metadata).encode("utf-8")
    print(
        stable_json(
            {
                "correction_ids": [item["correction_id"] for item in corrections],
                "revision_ref": REVISION_REF,
                "resolved_revision": resolved,
                "parquet_path": PARQUET_PATH,
                "metadata_sha256": hashlib.sha256(raw).hexdigest(),
                "liquidation_delta_type": "ledgerLiquidation",
            }
        ),
        flush=True,
    )
    return resolved, metadata


def find_convert_parquet_sibling(metadata: dict[str, object]) -> list[dict[str, object]]:
    siblings = metadata.get("siblings")
    if not isinstance(siblings, list):
        raise RuntimeError("convert/parquet revision metadata has no siblings list")
    matching = [
        item
        for item in siblings
        if isinstance(item, dict) and str(item.get("rfilename")) == PARQUET_PATH
    ]
    if len(matching) != 1:
        raise RuntimeError(f"expected one {PARQUET_PATH} sibling, found {len(matching)}")
    return matching


def iter_ledger_liquidation_deltas(
    node: Any,
) -> Iterator[tuple[dict[str, Any], list[str], str | None, str | None]]:
    """Yield only documented account-level ledgerLiquidation deltas."""
    if isinstance(node, list):
        for item in node:
            yield from iter_ledger_liquidation_deltas(item)
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
        if isinstance(delta, dict) and delta.get("type") == "ledgerLiquidation":
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
        yield from iter_ledger_liquidation_deltas(payload)


def validate_ledger_liquidation(
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
    if delta.get("type") != "ledgerLiquidation":
        raise ValueError(f"unexpected liquidation delta type {delta.get('type')!r}")
    account_value = engine.parse_number(delta.get("accountValue"), "accountValue")
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
        signed_size = engine.parse_number(item.get("szi"), "szi")
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

    explicit_notional: float | None = None
    raw_notional = delta.get("liquidatedNtlPos")
    if raw_notional not in (None, ""):
        parsed = engine.parse_number(raw_notional, "liquidatedNtlPos")
        if not math.isfinite(parsed) or parsed <= 0:
            raise ValueError("explicit liquidatedNtlPos must be finite-positive when present")
        explicit_notional = parsed

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
        "delta_type": "ledgerLiquidation",
        "liquidated_notional": explicit_notional,
        "liquidated_notional_source": (
            "EXPLICIT_SOURCE_FIELD"
            if explicit_notional is not None
            else "UNAVAILABLE_UNTIL_CAUSAL_PRICE_JOIN"
        ),
        "account_value": account_value,
        "leverage_type": leverage_type,
        "positions": positions,
    }
    return event, positions


def corrected_self_test() -> None:
    assert len(engine.candidate_paths()) == 36
    assert all("2026" not in path for path in engine.candidate_paths())
    synthetic = {
        "time": "2025-10-06T00:00:00.100000000",
        "hash": "0xabc",
        "inner": {
            "LedgerUpdate": {
                "users": ["0xUSER"],
                "delta": {
                    "type": "ledgerLiquidation",
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
    found = list(iter_ledger_liquidation_deltas(synthetic))
    assert len(found) == 1
    delta, users, event_hash, event_time = found[0]
    event, positions = validate_ledger_liquidation(
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
    assert event["liquidated_notional"] is None
    assert event["liquidated_notional_source"] == "UNAVAILABLE_UNTIL_CAUSAL_PRICE_JOIN"
    assert positions[0]["forced_flow_side"] == "SELL"
    assert positions[1]["forced_flow_side"] == "BUY"
    row = (
        "2025-10-06 00:00:00.250",
        "2025-10-06 00:00:00.100",
        123,
        json.dumps([synthetic]),
        "misc_events_by_block/hourly/20251006/0.lz4",
    )
    liquidations, malformed, row_error = engine.parse_event_row(row, 0)
    assert row_error is None
    assert malformed == []
    assert len(liquidations) == 1
    assert liquidations[0]["delta_type"] == "ledgerLiquidation"
    legacy = json.loads(json.dumps(synthetic))
    legacy["inner"]["LedgerUpdate"]["delta"]["type"] = "liquidation"
    assert list(iter_ledger_liquidation_deltas(legacy)) == []
    print("CORRECTED_LEDGER_LIQUIDATION_SELF_TEST_PASS")


engine.resolve_revision = resolve_convert_parquet_revision
engine.find_parquet_siblings = find_convert_parquet_sibling
engine.iter_liquidation_deltas = iter_ledger_liquidation_deltas
engine.validate_liquidation = validate_ledger_liquidation
engine.self_test = corrected_self_test


if __name__ == "__main__":
    raise SystemExit(engine.main())
