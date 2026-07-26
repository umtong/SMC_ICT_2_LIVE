from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import requests

CLAIM_ID = "CLM-20260726-2305-ML-XRPL-INFLOW-001"
USER_AGENT = "SMC-ICT-2-XRPL-exchange-inflow-source-gate/1.0"
RIPPLE_EPOCH_UNIX = 946684800
PARTIAL_PAYMENT_FLAG = 0x00020000
BIN_SECONDS = 15 * 60
PAGE_LIMIT = 400
MAX_PAGES = 250

RPC_ENDPOINTS = (
    "https://honeycluster.io/",
    "https://xrplcluster.com/",
    "https://s2.ripple.com:51234/",
)

WINDOWS = (
    ("2021-05-05T00:00:00Z", "2021-05-06T00:00:00Z"),
    ("2022-01-12T00:00:00Z", "2022-01-13T00:00:00Z"),
    ("2022-11-09T00:00:00Z", "2022-11-10T00:00:00Z"),
    ("2023-06-07T00:00:00Z", "2023-06-08T00:00:00Z"),
    ("2023-11-08T00:00:00Z", "2023-11-09T00:00:00Z"),
)

WALLETS = (
    {
        "exchange": "Binance",
        "role": "legacy_deposit",
        "account": "rEb8TK3gBgk5auZkwc6sHnwrGVJH8DuaLh",
    },
    {
        "exchange": "Binance",
        "role": "current_deposit_hot",
        "account": "rNxp4h8apvRis6mJf9Sh8C6iRxfrDWN7AV",
    },
    {
        "exchange": "Bitstamp",
        "role": "deposit_hot",
        "account": "rDsbeomae4FXwgQTJp9Rs64Qg9vDiTCdBv",
    },
    {
        "exchange": "Bybit",
        "role": "legacy_deposit",
        "account": "rJn2zAPdFA193sixJwuFixRkYDUtx3apQh",
    },
    {
        "exchange": "Bybit",
        "role": "current_deposit_hot",
        "account": "rMvCasZ9cohYrSZRNYPTZfoaaSUQMfgQ8G",
    },
)

FROZEN_ACCOUNTS = frozenset(wallet["account"] for wallet in WALLETS)


class SourceGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class InflowEvent:
    timestamp_ms: int
    close_time_iso: str
    ledger_index: int
    tx_hash: str
    exchange: str
    wallet: str
    source: str
    amount_xrp: float
    destination_tag: int | None
    external: bool
    tagged: bool

    @property
    def bin_start_ms(self) -> int:
        return (self.timestamp_ms // (BIN_SECONDS * 1000)) * (BIN_SECONDS * 1000)


@dataclass(frozen=True)
class RpcTarget:
    endpoint: str
    style: str


@dataclass
class RpcEvidence:
    request_id: str
    method: str
    endpoint: str
    style: str
    status_code: int
    sha256: str
    bytes: int
    raw_path: str


def stable_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )


def parse_iso(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def iso_to_ms(value: str) -> int:
    return int(parse_iso(value).timestamp() * 1000)


def ms_to_iso(value: int) -> str:
    return (
        dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def ripple_date_to_ms(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError("missing Ripple date")
    seconds = int(value)
    return (seconds + RIPPLE_EPOCH_UNIX) * 1000


def marker_fingerprint(marker: Any) -> str:
    return sha256_bytes(stable_json_bytes(marker))


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    )
    return session


def rpc_payload(method: str, params: dict[str, Any], style: str, request_id: str) -> dict[str, Any]:
    if style == "command":
        return {"id": request_id, "command": method, **params}
    if style == "method":
        return {"id": request_id, "method": method, "params": [params]}
    raise ValueError(f"unknown RPC style {style!r}")


def unwrap_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SourceGateError("RPC payload is not an object")
    result = payload.get("result", payload)
    if not isinstance(result, dict):
        raise SourceGateError("RPC result is not an object")
    status = payload.get("status") or result.get("status")
    if status == "error" or result.get("error"):
        raise SourceGateError(
            f"RPC error {result.get('error')!r}: {result.get('error_message')!r}"
        )
    return result


def rpc_call(
    session: requests.Session,
    method: str,
    params: dict[str, Any],
    *,
    request_id: str,
    raw_dir: Path,
    preferred: RpcTarget | None = None,
    attempts: int = 3,
) -> tuple[dict[str, Any], RpcEvidence, RpcTarget]:
    targets: list[RpcTarget] = []
    if preferred is not None:
        targets.append(preferred)
    for endpoint in RPC_ENDPOINTS:
        for style in ("command", "method"):
            target = RpcTarget(endpoint, style)
            if target not in targets:
                targets.append(target)

    last_error: Exception | None = None
    for target in targets:
        for attempt in range(attempts):
            payload = rpc_payload(method, params, target.style, request_id)
            try:
                response = session.post(
                    target.endpoint,
                    json=payload,
                    timeout=(20, 120),
                )
                body = response.content
                safe_id = "".join(
                    ch if ch.isalnum() or ch in "-_" else "_" for ch in request_id
                )
                raw_path = raw_dir / (
                    f"{safe_id}-{target.endpoint.split('//', 1)[-1].split('/', 1)[0]}-"
                    f"{target.style}-attempt-{attempt + 1}.json"
                )
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(body)
                if response.status_code == 429 or response.status_code >= 500:
                    raise SourceGateError(f"retryable HTTP {response.status_code}")
                response.raise_for_status()
                result = unwrap_result(response.json())
                evidence = RpcEvidence(
                    request_id=request_id,
                    method=method,
                    endpoint=target.endpoint,
                    style=target.style,
                    status_code=response.status_code,
                    sha256=sha256_bytes(body),
                    bytes=len(body),
                    raw_path=str(raw_path),
                )
                return result, evidence, target
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(0.75 * (2**attempt))
    raise SourceGateError(f"RPC {method} failed for {request_id}: {last_error!r}")


def ledger_for_time(
    session: requests.Session,
    iso: str,
    raw_dir: Path,
    preferred: RpcTarget | None,
) -> tuple[dict[str, Any], RpcEvidence, RpcTarget]:
    result, evidence, used = rpc_call(
        session,
        "ledger_index",
        {"date": iso},
        request_id=f"ledger-index-{iso}",
        raw_dir=raw_dir,
        preferred=preferred,
    )
    if not bool(result.get("validated", False)):
        raise SourceGateError(f"non-validated ledger_index result for {iso}")
    ledger_index = int(result["ledger_index"])
    closed = result.get("closed")
    if not isinstance(closed, str):
        raise SourceGateError(f"ledger_index result lacks closed timestamp for {iso}")
    return (
        {
            "requested": iso,
            "ledger_index": ledger_index,
            "ledger_hash": result.get("ledger_hash"),
            "closed": closed,
            "validated": True,
        },
        evidence,
        used,
    )


def account_exists(
    session: requests.Session,
    wallet: dict[str, str],
    raw_dir: Path,
    preferred: RpcTarget | None,
) -> tuple[dict[str, Any], RpcTarget]:
    result, evidence, used = rpc_call(
        session,
        "account_info",
        {
            "account": wallet["account"],
            "ledger_index": "validated",
            "strict": True,
            "api_version": 2,
        },
        request_id=f"account-info-{wallet['exchange']}-{wallet['role']}",
        raw_dir=raw_dir,
        preferred=preferred,
    )
    account_data = result.get("account_data")
    account_ok = (
        isinstance(account_data, dict)
        and account_data.get("Account") == wallet["account"]
        and bool(result.get("validated", True))
    )
    return (
        {
            "wallet": wallet,
            "exists": account_ok,
            "ledger_index": result.get("ledger_index"),
            "validated": result.get("validated", True),
            "response": asdict(evidence),
        },
        used,
    )


def transaction_json(item: dict[str, Any]) -> dict[str, Any]:
    tx = item.get("tx_json")
    if not isinstance(tx, dict):
        tx = item.get("tx")
    if not isinstance(tx, dict):
        raise ValueError("transaction JSON missing")
    return tx


def transaction_meta(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("transaction metadata missing")
    return meta


def native_delivered_xrp(tx: dict[str, Any], meta: dict[str, Any]) -> float:
    delivered = meta.get("delivered_amount")
    if delivered is None:
        delivered = meta.get("DeliveredAmount")
    if isinstance(delivered, str) and delivered != "unavailable":
        drops = int(delivered)
        if drops <= 0:
            raise ValueError("non-positive delivered XRP")
        return drops / 1_000_000.0
    if isinstance(delivered, dict):
        raise ValueError("delivered asset is not native XRP")

    flags = int(tx.get("Flags", 0))
    if flags & PARTIAL_PAYMENT_FLAG:
        raise ValueError("partial payment lacks delivered native amount")
    amount = tx.get("Amount")
    if not isinstance(amount, str):
        amount = tx.get("DeliverMax")
    if not isinstance(amount, str):
        raise ValueError("native XRP amount missing")
    drops = int(amount)
    if drops <= 0:
        raise ValueError("non-positive native XRP amount")
    return drops / 1_000_000.0


def transaction_time_ms(item: dict[str, Any], tx: dict[str, Any]) -> tuple[int, str]:
    close_time_iso = item.get("close_time_iso")
    if isinstance(close_time_iso, str):
        timestamp_ms = iso_to_ms(close_time_iso)
        return timestamp_ms, ms_to_iso(timestamp_ms)
    timestamp_ms = ripple_date_to_ms(tx.get("date"))
    return timestamp_ms, ms_to_iso(timestamp_ms)


def parse_inflow_event(
    item: Any,
    wallet: dict[str, str],
    *,
    result_validated: bool,
) -> InflowEvent:
    if not isinstance(item, dict):
        raise ValueError("account_tx item is not an object")
    tx = transaction_json(item)
    meta = transaction_meta(item)
    validated = item.get("validated", result_validated)
    if not bool(validated):
        raise ValueError("transaction is not validated")
    if tx.get("TransactionType") != "Payment":
        raise ValueError("not a Payment")
    if meta.get("TransactionResult") != "tesSUCCESS":
        raise ValueError("payment did not succeed")
    if tx.get("Destination") != wallet["account"]:
        raise ValueError("payment destination does not match queried wallet")
    source = tx.get("Account")
    if not isinstance(source, str) or not source:
        raise ValueError("payment source missing")
    amount_xrp = native_delivered_xrp(tx, meta)
    timestamp_ms, close_time_iso = transaction_time_ms(item, tx)
    ledger_index_raw = item.get("ledger_index", tx.get("ledger_index"))
    ledger_index = int(ledger_index_raw)
    tx_hash = item.get("hash") or tx.get("hash")
    if not isinstance(tx_hash, str) or not tx_hash:
        tx_hash = sha256_bytes(stable_json_bytes({"tx": tx, "meta": meta}))
    destination_tag = tx.get("DestinationTag")
    if destination_tag is not None:
        destination_tag = int(destination_tag)
    return InflowEvent(
        timestamp_ms=timestamp_ms,
        close_time_iso=close_time_iso,
        ledger_index=ledger_index,
        tx_hash=tx_hash,
        exchange=wallet["exchange"],
        wallet=wallet["account"],
        source=source,
        amount_xrp=amount_xrp,
        destination_tag=destination_tag,
        external=source not in FROZEN_ACCOUNTS,
        tagged=destination_tag is not None,
    )


def fetch_account_window(
    session: requests.Session,
    wallet: dict[str, str],
    start_ledger: int,
    end_ledger: int,
    start_ms: int,
    end_ms: int,
    raw_dir: Path,
    preferred: RpcTarget | None,
) -> tuple[dict[str, Any], RpcTarget]:
    marker: Any = None
    marker_seen: set[str] = set()
    response_hashes: list[str] = []
    request_evidence: list[dict[str, Any]] = []
    events: dict[str, InflowEvent] = {}
    parse_errors: list[str] = []
    used = preferred
    page = 0
    filter_mode = "server_tx_type_payment"

    while True:
        if page >= MAX_PAGES:
            return (
                {
                    "wallet": wallet,
                    "start_ledger": start_ledger,
                    "end_ledger": end_ledger,
                    "page_count": page,
                    "truncated": True,
                    "unresolved_marker": marker,
                    "filter_mode": filter_mode,
                    "events": [asdict(event) for event in sorted(events.values(), key=lambda x: (x.timestamp_ms, x.tx_hash))],
                    "parse_errors": parse_errors,
                    "response_hash_root": sha256_bytes(stable_json_bytes(response_hashes)),
                    "responses": request_evidence,
                },
                used if used is not None else RpcTarget(RPC_ENDPOINTS[0], "command"),
            )

        params: dict[str, Any] = {
            "account": wallet["account"],
            "ledger_index_min": start_ledger,
            "ledger_index_max": end_ledger,
            "binary": False,
            "forward": True,
            "limit": PAGE_LIMIT,
            "api_version": 2,
        }
        if filter_mode == "server_tx_type_payment":
            params["tx_type"] = "Payment"
        if marker is not None:
            params["marker"] = marker

        request_id = (
            f"account-tx-{wallet['exchange']}-{wallet['role']}-"
            f"{start_ledger}-{end_ledger}-page-{page + 1}-{filter_mode}"
        )
        try:
            result, evidence, used = rpc_call(
                session,
                "account_tx",
                params,
                request_id=request_id,
                raw_dir=raw_dir,
                preferred=used,
            )
        except SourceGateError:
            if page == 0 and filter_mode == "server_tx_type_payment":
                filter_mode = "local_payment_filter"
                continue
            raise

        if not bool(result.get("validated", False)):
            raise SourceGateError(f"account_tx result not validated for {wallet['account']}")
        actual_min = int(result.get("ledger_index_min", start_ledger))
        actual_max = int(result.get("ledger_index_max", end_ledger))
        if actual_min > start_ledger or actual_max < end_ledger:
            raise SourceGateError(
                f"server range {actual_min}:{actual_max} does not contain requested "
                f"{start_ledger}:{end_ledger}"
            )

        response_hashes.append(evidence.sha256)
        request_evidence.append(asdict(evidence))
        transactions = result.get("transactions", [])
        if not isinstance(transactions, list):
            raise SourceGateError("account_tx transactions is not a list")
        for index, item in enumerate(transactions):
            try:
                event = parse_inflow_event(
                    item,
                    wallet,
                    result_validated=bool(result.get("validated", False)),
                )
                if start_ms <= event.timestamp_ms < end_ms:
                    events[event.tx_hash] = event
            except Exception as exc:
                if len(parse_errors) < 40:
                    parse_errors.append(f"page={page + 1} item={index}: {exc!r}")

        page += 1
        next_marker = result.get("marker")
        if next_marker is None:
            break
        fingerprint = marker_fingerprint(next_marker)
        if fingerprint in marker_seen:
            raise SourceGateError(f"repeated account_tx marker for {wallet['account']}")
        marker_seen.add(fingerprint)
        marker = next_marker
        time.sleep(0.04)

    ordered = sorted(events.values(), key=lambda event: (event.timestamp_ms, event.tx_hash))
    return (
        {
            "wallet": wallet,
            "start_ledger": start_ledger,
            "end_ledger": end_ledger,
            "page_count": page,
            "truncated": False,
            "unresolved_marker": None,
            "filter_mode": filter_mode,
            "events": [asdict(event) for event in ordered],
            "parse_errors": parse_errors,
            "response_hash_root": sha256_bytes(stable_json_bytes(response_hashes)),
            "responses": request_evidence,
        },
        used if used is not None else RpcTarget(RPC_ENDPOINTS[0], "command"),
    )


def qualified_events(events: Iterable[InflowEvent]) -> list[InflowEvent]:
    return [event for event in events if event.external and event.tagged]


def summarize(
    window_reports: list[dict[str, Any]],
    account_checks: list[dict[str, Any]],
) -> dict[str, Any]:
    all_events: dict[str, InflowEvent] = {}
    for window in window_reports:
        for account_report in window["accounts"]:
            for raw in account_report["events"]:
                event = InflowEvent(**raw)
                all_events[event.tx_hash] = event
    ordered = sorted(all_events.values(), key=lambda event: (event.timestamp_ms, event.tx_hash))
    primary = qualified_events(ordered)

    per_window: list[dict[str, Any]] = []
    for window in window_reports:
        events = [
            InflowEvent(**raw)
            for report in window["accounts"]
            for raw in report["events"]
        ]
        primary_events = qualified_events(events)
        bins = {
            (event.exchange, event.bin_start_ms)
            for event in primary_events
        }
        per_window.append(
            {
                "start": window["start"],
                "end": window["end"],
                "external_tagged_count": len(primary_events),
                "external_tagged_xrp": sum(event.amount_xrp for event in primary_events),
                "positive_exchange_bins": len(bins),
                "distinct_external_sources": len({event.source for event in primary_events}),
                "exchanges": sorted({event.exchange for event in primary_events}),
                "query_truncated": any(report["truncated"] for report in window["accounts"]),
            }
        )

    per_exchange: dict[str, dict[str, Any]] = {}
    for exchange in sorted({wallet["exchange"] for wallet in WALLETS}):
        exchange_events = [event for event in primary if event.exchange == exchange]
        dates = {
            ms_to_iso(event.timestamp_ms)[:10]
            for event in exchange_events
        }
        bins = {(ms_to_iso(event.timestamp_ms)[:10], event.bin_start_ms) for event in exchange_events}
        per_exchange[exchange] = {
            "external_tagged_count": len(exchange_events),
            "external_tagged_xrp": sum(event.amount_xrp for event in exchange_events),
            "distinct_sources": len({event.source for event in exchange_events}),
            "date_count": len(dates),
            "positive_bins": len(bins),
        }

    positive_bins = {
        (event.exchange, ms_to_iso(event.timestamp_ms)[:10], event.bin_start_ms)
        for event in primary
    }
    qualifying_dates = sum(
        row["external_tagged_count"] >= 25 and row["positive_exchange_bins"] >= 10
        for row in per_window
    )
    all_boundaries_ok = all(window["boundaries_validated"] for window in window_reports)
    no_truncation = all(
        not account_report["truncated"]
        for window in window_reports
        for account_report in window["accounts"]
    )
    accounts_exist = all(check["exists"] for check in account_checks)
    exchange_gate = all(
        row["external_tagged_count"] >= 25 and row["date_count"] >= 3
        for row in per_exchange.values()
    )
    source_gate_pass = (
        accounts_exist
        and all_boundaries_ok
        and no_truncation
        and qualifying_dates >= 4
        and len(primary) >= 500
        and len({event.source for event in primary}) >= 100
        and len(positive_bins) >= 150
        and exchange_gate
    )

    return {
        "accounts_exist": accounts_exist,
        "all_boundaries_validated": all_boundaries_ok,
        "no_query_truncation": no_truncation,
        "total_native_inbound_count": len(ordered),
        "total_native_inbound_xrp": sum(event.amount_xrp for event in ordered),
        "external_count": sum(event.external for event in ordered),
        "external_tagged_count": len(primary),
        "external_tagged_xrp": sum(event.amount_xrp for event in primary),
        "distinct_external_sources": len({event.source for event in primary}),
        "positive_exchange_date_bins": len(positive_bins),
        "qualifying_date_count": qualifying_dates,
        "per_window": per_window,
        "per_exchange": per_exchange,
        "exchange_gate": exchange_gate,
        "source_gate_pass": source_gate_pass,
        "event_hash_root": sha256_bytes(
            stable_json_bytes([asdict(event) for event in primary])
        ),
    }


def build_manifest(output: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name not in {"SOURCE_MANIFEST.json", "OUTPUT_SHA256SUMS.txt"}:
            files.append(
                {
                    "path": str(path.relative_to(output)),
                    "sha256": sha256_bytes(path.read_bytes()),
                    "bytes": path.stat().st_size,
                }
            )
    return {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "files": files,
        "manifest_root": sha256_bytes(stable_json_bytes(files)),
    }


def run(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = make_session()
    preferred: RpcTarget | None = None

    account_checks: list[dict[str, Any]] = []
    for wallet in WALLETS:
        check, preferred = account_exists(session, wallet, raw_dir, preferred)
        account_checks.append(check)

    window_reports: list[dict[str, Any]] = []
    events_path = output / "EVENTS.jsonl"
    event_lines: list[str] = []
    for start_iso, end_iso in WINDOWS:
        start_info, start_evidence, preferred = ledger_for_time(
            session, start_iso, raw_dir, preferred
        )
        end_info, end_evidence, preferred = ledger_for_time(
            session, end_iso, raw_dir, preferred
        )
        start_ledger = int(start_info["ledger_index"])
        end_ledger = int(end_info["ledger_index"])
        if end_ledger <= start_ledger:
            raise SourceGateError(f"non-positive ledger window {start_iso} to {end_iso}")
        start_ms = iso_to_ms(start_iso)
        end_ms = iso_to_ms(end_iso)
        accounts: list[dict[str, Any]] = []
        for wallet in WALLETS:
            report, preferred = fetch_account_window(
                session,
                wallet,
                start_ledger,
                end_ledger,
                start_ms,
                end_ms,
                raw_dir,
                preferred,
            )
            accounts.append(report)
            for event in report["events"]:
                event_lines.append(json.dumps(event, sort_keys=True, separators=(",", ":")))
        window_reports.append(
            {
                "start": start_iso,
                "end": end_iso,
                "start_boundary": start_info,
                "end_boundary": end_info,
                "boundary_responses": [asdict(start_evidence), asdict(end_evidence)],
                "boundaries_validated": bool(start_info["validated"] and end_info["validated"]),
                "accounts": accounts,
            }
        )

    events_path.write_text("\n".join(event_lines) + ("\n" if event_lines else ""), encoding="utf-8")
    summary = summarize(window_reports, account_checks)
    source_gate_pass = bool(summary["source_gate_pass"])
    decision = (
        "OPEN_FROZEN_PRE2024_ML_STAGE"
        if source_gate_pass
        else "CLOSE_XRPL_EXCHANGE_INFLOW_SOURCE_BEFORE_MARKET_OUTCOMES"
    )
    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "phase": "OUTCOME_SEALED_SOURCE_GATE",
        "source_gate_pass": source_gate_pass,
        "scientific_decision": decision,
        "rpc_endpoints": list(RPC_ENDPOINTS),
        "windows": list(WINDOWS),
        "wallets": [dict(wallet) for wallet in WALLETS],
        "account_checks": account_checks,
        "summary": summary,
        "window_reports": window_reports,
        "bybit_market_opened": False,
        "future_return_opened": False,
        "model_fitted": False,
        "strategy_pnl_opened": False,
        "official_2024_opened": False,
        "official_2026_opened": False,
        "credentials_opened": False,
        "orders_submitted": False,
        "fatal_error": None,
    }
    write_json(output / "SOURCE_GATE_RESULT.json", result)
    write_json(output / "SOURCE_MANIFEST.json", build_manifest(output))
    return result


def self_test() -> None:
    assert ripple_date_to_ms(0) == 946684800000
    marker = {"ledger": 123, "seq": 4}
    assert marker_fingerprint(marker) == marker_fingerprint({"seq": 4, "ledger": 123})
    wallet = dict(WALLETS[0])
    item = {
        "validated": True,
        "ledger_index": 100,
        "hash": "ABC",
        "close_time_iso": "2023-01-01T00:01:00Z",
        "tx_json": {
            "Account": "rExternal",
            "Destination": wallet["account"],
            "DestinationTag": 123,
            "TransactionType": "Payment",
            "Amount": "2500000",
        },
        "meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": "2500000"},
    }
    event = parse_inflow_event(item, wallet, result_validated=True)
    assert math.isclose(event.amount_xrp, 2.5)
    assert event.external and event.tagged
    print("self-test: ok")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        parser.error("--output is required unless --self-test is used")
    try:
        result = run(args.output)
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        result = {
            "schema_version": 1,
            "claim_id": CLAIM_ID,
            "phase": "OUTCOME_SEALED_SOURCE_GATE",
            "source_gate_pass": False,
            "scientific_decision": "CLOSE_XRPL_EXCHANGE_INFLOW_SOURCE_BEFORE_MARKET_OUTCOMES",
            "bybit_market_opened": False,
            "future_return_opened": False,
            "model_fitted": False,
            "strategy_pnl_opened": False,
            "official_2024_opened": False,
            "official_2026_opened": False,
            "credentials_opened": False,
            "orders_submitted": False,
            "fatal_error": repr(exc),
        }
        write_json(args.output / "SOURCE_GATE_RESULT.json", result)
        write_json(args.output / "SOURCE_MANIFEST.json", build_manifest(args.output))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
