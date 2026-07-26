from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import random
import statistics
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import requests

CLAIM_ID = "CLM-20260726-2250-ML-XRPL-DEX-001"
USER_AGENT = "SMC-ICT-2-XRPL-DEX-source-gate/1.0"
XRPL_TO_BASE = "https://api.xrpl.to/v1"
CLIO_ENDPOINTS = (
    "https://honeycluster.io/",
    "https://xrplcluster.com/",
    "https://s2.ripple.com:51234/",
)
INTERVAL = "15m"
BAR_SECONDS = 15 * 60
WINDOWS = (
    ("2021-05-03T00:00:00Z", "2021-05-10T00:00:00Z"),
    ("2022-01-10T00:00:00Z", "2022-01-17T00:00:00Z"),
    ("2022-11-07T00:00:00Z", "2022-11-14T00:00:00Z"),
    ("2023-06-05T00:00:00Z", "2023-06-12T00:00:00Z"),
    ("2023-11-06T00:00:00Z", "2023-11-13T00:00:00Z"),
)
TOKENS = (
    {
        "name": "GateHub USD",
        "issuer": "rhub8VRN55s94qWKDv6jmDy1pUykJzF3wq",
        "currency": "USD",
    },
    {
        "name": "Bitstamp USD",
        "issuer": "rvYAfWj5gh67oV6fW32ZzP3Aw4Eubs59B",
        "currency": "USD",
    },
)


class SourceGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candle:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def validate(self) -> None:
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(math.isfinite(x) for x in values):
            raise ValueError("non-finite candle")
        if self.timestamp_ms <= 0:
            raise ValueError("non-positive timestamp")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("non-positive OHLC")
        if self.volume < 0:
            raise ValueError("negative volume")
        if self.high + 1e-15 < max(self.open, self.close, self.low):
            raise ValueError("high below OHLC")
        if self.low - 1e-15 > min(self.open, self.close, self.high):
            raise ValueError("low above OHLC")


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


def iso_to_ms(value: str) -> int:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.timestamp() * 1000)


def ms_to_iso(value: int) -> str:
    return dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def token_md5(issuer: str, currency: str) -> str:
    return hashlib.md5(f"{issuer}_{currency}".encode("utf-8")).hexdigest()


def _to_float(value: Any, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field} missing")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} non-finite")
    return number


def _timestamp_ms(value: Any) -> int:
    if value is None or isinstance(value, bool):
        raise ValueError("timestamp missing")
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("timestamp non-finite")
        if number < 10_000_000_000:
            number *= 1000
        return int(number)
    text = str(value).strip()
    if not text:
        raise ValueError("timestamp empty")
    try:
        return _timestamp_ms(float(text))
    except ValueError:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.timestamp() * 1000)


def parse_candle_row(row: Any) -> Candle:
    if isinstance(row, (list, tuple)) and len(row) >= 6:
        candle = Candle(
            timestamp_ms=_timestamp_ms(row[0]),
            open=_to_float(row[1], "open"),
            high=_to_float(row[2], "high"),
            low=_to_float(row[3], "low"),
            close=_to_float(row[4], "close"),
            volume=_to_float(row[5], "volume"),
        )
        candle.validate()
        return candle
    if isinstance(row, dict):
        def pick(*names: str) -> Any:
            for name in names:
                if name in row:
                    return row[name]
            return None

        candle = Candle(
            timestamp_ms=_timestamp_ms(pick("timestamp", "time", "t", "date", "start", "openTime", "open_time")),
            open=_to_float(pick("open", "o"), "open"),
            high=_to_float(pick("high", "h"), "high"),
            low=_to_float(pick("low", "l"), "low"),
            close=_to_float(pick("close", "c"), "close"),
            volume=_to_float(pick("volume", "v", "vol", "volumeXrp", "volume_xrp"), "volume"),
        )
        candle.validate()
        return candle
    raise ValueError(f"unsupported candle row type {type(row)!r}")


def _candidate_lists(node: Any, depth: int = 0) -> Iterable[list[Any]]:
    if depth > 6:
        return
    if isinstance(node, list):
        yield node
        return
    if not isinstance(node, dict):
        return
    preferred = ("ohlc", "candles", "rows", "data", "result", "items", "history")
    seen: set[int] = set()
    for key in preferred:
        child = node.get(key)
        if id(child) in seen:
            continue
        seen.add(id(child))
        yield from _candidate_lists(child, depth + 1)
    for child in node.values():
        if id(child) in seen:
            continue
        seen.add(id(child))
        yield from _candidate_lists(child, depth + 1)


def parse_candles(payload: Any) -> tuple[list[Candle], list[str]]:
    errors: list[str] = []
    best: list[Candle] = []
    for candidate in _candidate_lists(payload):
        parsed: list[Candle] = []
        local_errors: list[str] = []
        for index, row in enumerate(candidate):
            try:
                parsed.append(parse_candle_row(row))
            except Exception as exc:
                if len(local_errors) < 10:
                    local_errors.append(f"row[{index}]: {exc!r}")
        if len(parsed) > len(best):
            best = parsed
            errors = local_errors
    dedup = {c.timestamp_ms: c for c in best}
    return sorted(dedup.values(), key=lambda c: c.timestamp_ms), errors


def find_identity(payload: Any, issuer: str, currency: str) -> bool:
    if isinstance(payload, dict):
        issuer_value = payload.get("issuer")
        currency_value = payload.get("currency")
        if (
            isinstance(issuer_value, str)
            and issuer_value == issuer
            and isinstance(currency_value, str)
            and currency_value.upper() == currency.upper()
        ):
            return True
        return any(find_identity(child, issuer, currency) for child in payload.values())
    if isinstance(payload, list):
        return any(find_identity(child, issuer, currency) for child in payload)
    return False


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
    )
    return session


def get_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None,
    raw_dir: Path,
    label: str,
    attempts: int = 4,
) -> tuple[Any, dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=(20, 90))
            body = response.content
            suffix = f"{label}-attempt-{attempt + 1}.json"
            raw_path = raw_dir / suffix
            raw_path.write_bytes(body)
            meta = {
                "url": response.url,
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
                "sha256": sha256_bytes(body),
                "bytes": len(body),
                "raw_path": str(raw_path),
            }
            if response.status_code == 429 or response.status_code >= 500:
                raise SourceGateError(f"retryable HTTP {response.status_code}")
            response.raise_for_status()
            return response.json(), meta
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (2**attempt))
    raise SourceGateError(f"GET failed {url}: {last_error!r}")


def fetch_token_metadata(
    session: requests.Session,
    token: dict[str, str],
    raw_dir: Path,
) -> dict[str, Any]:
    md5 = token_md5(token["issuer"], token["currency"])
    variants = (
        f"{XRPL_TO_BASE}/token/{md5}",
        f"{XRPL_TO_BASE}/token/{token['issuer']}_{token['currency']}",
    )
    attempts: list[dict[str, Any]] = []
    for index, url in enumerate(variants):
        try:
            payload, meta = get_json(
                session,
                url,
                params=None,
                raw_dir=raw_dir,
                label=f"token-{token['name'].lower().replace(' ', '-')}-{index}",
            )
            identity_ok = find_identity(payload, token["issuer"], token["currency"])
            attempts.append({"ok": True, "identity_ok": identity_ok, "meta": meta})
            if identity_ok:
                return {
                    "md5": md5,
                    "identity_ok": True,
                    "selected": attempts[-1],
                    "attempts": attempts,
                }
        except Exception as exc:
            attempts.append({"ok": False, "error": repr(exc), "url": url})
    return {"md5": md5, "identity_ok": False, "attempts": attempts}


def ohlc_param_variants(start_ms: int, end_ms: int) -> tuple[dict[str, Any], ...]:
    return (
        {"interval": INTERVAL, "limit": 5000, "start": start_ms, "end": end_ms},
        {"interval": INTERVAL, "limit": 5000, "startTime": start_ms, "endTime": end_ms},
        {
            "interval": INTERVAL,
            "limit": 5000,
            "from": start_ms // 1000,
            "to": end_ms // 1000,
        },
    )


def fetch_window(
    session: requests.Session,
    token: dict[str, str],
    md5: str,
    start_iso: str,
    end_iso: str,
    raw_dir: Path,
) -> dict[str, Any]:
    start_ms = iso_to_ms(start_iso)
    end_ms = iso_to_ms(end_iso)
    url = f"{XRPL_TO_BASE}/ohlc/{md5}"
    attempts: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    selected_candles: list[Candle] = []
    for variant_index, params in enumerate(ohlc_param_variants(start_ms, end_ms)):
        label = (
            f"ohlc-{token['name'].lower().replace(' ', '-')}-"
            f"{start_iso[:10]}-v{variant_index}"
        )
        try:
            payload, meta = get_json(
                session,
                url,
                params=params,
                raw_dir=raw_dir,
                label=label,
            )
            candles, parse_errors = parse_candles(payload)
            in_window = [
                c for c in candles if start_ms <= c.timestamp_ms < end_ms
            ]
            record = {
                "ok": True,
                "params": params,
                "meta": meta,
                "parsed_count": len(candles),
                "in_window_count": len(in_window),
                "parse_errors": parse_errors,
                "parsed_min": ms_to_iso(candles[0].timestamp_ms) if candles else None,
                "parsed_max": ms_to_iso(candles[-1].timestamp_ms) if candles else None,
            }
            attempts.append(record)
            if len(in_window) > len(selected_candles):
                selected = record
                selected_candles = in_window
        except Exception as exc:
            attempts.append({"ok": False, "params": params, "error": repr(exc)})
    positive = [c for c in selected_candles if c.volume > 0]
    diffs = [
        (b.timestamp_ms - a.timestamp_ms) // 1000
        for a, b in zip(selected_candles, selected_candles[1:])
        if b.timestamp_ms > a.timestamp_ms
    ]
    cadence_mode = statistics.mode(diffs) if diffs else None
    return {
        "start": start_iso,
        "end": end_iso,
        "attempts": attempts,
        "selected": selected,
        "candles": [asdict(c) for c in selected_candles],
        "count": len(selected_candles),
        "positive_volume_count": len(positive),
        "volume_sum": sum(c.volume for c in positive),
        "cadence_mode_seconds": cadence_mode,
        "min_timestamp": ms_to_iso(selected_candles[0].timestamp_ms) if selected_candles else None,
        "max_timestamp": ms_to_iso(selected_candles[-1].timestamp_ms) if selected_candles else None,
    }


def rpc_payload(command: str, params: dict[str, Any], style: str, request_id: str) -> dict[str, Any]:
    if style == "command":
        return {"id": request_id, "command": command, **params}
    if style == "method":
        return {"id": request_id, "method": command, "params": [params]}
    raise ValueError(style)


def rpc_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SourceGateError("RPC response is not an object")
    result = payload.get("result", payload)
    if not isinstance(result, dict):
        raise SourceGateError("RPC result is not an object")
    status = payload.get("status") or result.get("status")
    if status == "error" or "error" in result:
        raise SourceGateError(f"RPC error: {result.get('error')!r} {result.get('error_message')!r}")
    return result


def rpc_call(
    session: requests.Session,
    command: str,
    params: dict[str, Any],
    *,
    request_id: str,
    preferred: tuple[str, str] | None = None,
    attempts: int = 3,
) -> tuple[dict[str, Any], dict[str, Any], tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    if preferred is not None:
        targets.append(preferred)
    for endpoint in CLIO_ENDPOINTS:
        for style in ("command", "method"):
            item = (endpoint, style)
            if item not in targets:
                targets.append(item)
    last_error: Exception | None = None
    for endpoint, style in targets:
        for attempt in range(attempts):
            body_obj = rpc_payload(command, params, style, request_id)
            try:
                response = session.post(
                    endpoint,
                    json=body_obj,
                    timeout=(20, 90),
                    headers={"Content-Type": "application/json"},
                )
                body = response.content
                if response.status_code == 429 or response.status_code >= 500:
                    raise SourceGateError(f"retryable HTTP {response.status_code}")
                response.raise_for_status()
                payload = response.json()
                result = rpc_result(payload)
                meta = {
                    "endpoint": endpoint,
                    "style": style,
                    "status_code": response.status_code,
                    "sha256": sha256_bytes(body),
                    "bytes": len(body),
                }
                return result, meta, (endpoint, style)
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (2**attempt))
    raise SourceGateError(f"RPC {command} failed: {last_error!r}")


def ledger_for_time(
    session: requests.Session,
    timestamp_ms: int,
    preferred: tuple[str, str] | None,
) -> tuple[dict[str, Any], dict[str, Any], tuple[str, str]]:
    iso = dt.datetime.fromtimestamp(timestamp_ms / 1000, tz=dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    result, meta, used = rpc_call(
        session,
        "ledger_index",
        {"date": iso},
        request_id=f"ledger-index-{timestamp_ms}",
        preferred=preferred,
    )
    if not result.get("validated", True):
        raise SourceGateError("ledger_index returned non-validated result")
    index = result.get("ledger_index")
    if not isinstance(index, int):
        index = int(index)
    return {"requested": iso, "ledger_index": index, "closed": result.get("closed"), "ledger_hash": result.get("ledger_hash")}, meta, used


def matching_book_change(
    result: dict[str, Any],
    issuer: str,
    currency: str,
) -> list[dict[str, Any]]:
    target = f"{issuer}/{currency}"
    changes = result.get("changes", [])
    if not isinstance(changes, list):
        return []
    found: list[dict[str, Any]] = []
    for item in changes:
        if not isinstance(item, dict):
            continue
        currencies = {item.get("currency_a"), item.get("currency_b")}
        if "XRP_drops" not in currencies or target not in currencies:
            continue
        try:
            volume_a = _to_float(item.get("volume_a"), "volume_a")
            volume_b = _to_float(item.get("volume_b"), "volume_b")
            close = _to_float(item.get("close"), "close")
        except Exception:
            continue
        if volume_a <= 0 or volume_b <= 0 or close <= 0:
            continue
        normalized = dict(item)
        normalized["ledger_index"] = int(result.get("ledger_index"))
        normalized["ledger_time"] = result.get("ledger_time")
        if item.get("currency_a") == "XRP_drops":
            normalized["xrp_per_token_close"] = close / 1_000_000.0
            normalized["xrp_volume"] = volume_a / 1_000_000.0
            normalized["token_volume"] = volume_b
        else:
            normalized["xrp_per_token_close"] = 1.0 / (close * 1_000_000.0)
            normalized["xrp_volume"] = volume_b / 1_000_000.0
            normalized["token_volume"] = volume_a
        found.append(normalized)
    return found


def verify_candle_on_clio(
    session: requests.Session,
    token: dict[str, str],
    candle: Candle,
    preferred: tuple[str, str] | None,
    *,
    max_ledgers: int = 420,
) -> dict[str, Any]:
    interpretations = (
        ("timestamp_is_open", candle.timestamp_ms, candle.timestamp_ms + BAR_SECONDS * 1000),
        ("timestamp_is_close", candle.timestamp_ms - BAR_SECONDS * 1000, candle.timestamp_ms),
    )
    all_attempts: list[dict[str, Any]] = []
    selected_preferred = preferred
    for interpretation, start_ms, end_ms in interpretations:
        try:
            start_info, start_meta, selected_preferred = ledger_for_time(
                session, start_ms, selected_preferred
            )
            end_info, end_meta, selected_preferred = ledger_for_time(
                session, end_ms, selected_preferred
            )
            lo = int(start_info["ledger_index"]) + 1
            hi = int(end_info["ledger_index"])
            span = max(0, hi - lo + 1)
            if span > max_ledgers:
                raise SourceGateError(f"ledger span {span} exceeds cap {max_ledgers}")
            matches: list[dict[str, Any]] = []
            response_hashes: list[str] = []
            errors: list[str] = []
            for ledger_index in range(lo, hi + 1):
                try:
                    result, meta, selected_preferred = rpc_call(
                        session,
                        "book_changes",
                        {"ledger_index": ledger_index},
                        request_id=f"book-changes-{ledger_index}",
                        preferred=selected_preferred,
                        attempts=2,
                    )
                    response_hashes.append(meta["sha256"])
                    matches.extend(
                        matching_book_change(
                            result, token["issuer"], token["currency"]
                        )
                    )
                except Exception as exc:
                    if len(errors) < 20:
                        errors.append(f"{ledger_index}: {exc!r}")
                time.sleep(0.025)
            attempt = {
                "interpretation": interpretation,
                "start": start_info,
                "end": end_info,
                "start_rpc": start_meta,
                "end_rpc": end_meta,
                "ledger_span": span,
                "queried_ledgers": span,
                "rpc_response_hash_root": sha256_bytes(
                    stable_json_bytes(response_hashes)
                ),
                "rpc_error_count": len(errors),
                "rpc_errors": errors,
                "match_count": len(matches),
                "matches": matches,
            }
            all_attempts.append(attempt)
            if matches:
                return {
                    "confirmed": True,
                    "token": token,
                    "candle": asdict(candle),
                    "attempts": all_attempts,
                    "selected": attempt,
                    "preferred_rpc": selected_preferred,
                }
        except Exception as exc:
            all_attempts.append(
                {"interpretation": interpretation, "error": repr(exc)}
            )
    return {
        "confirmed": False,
        "token": token,
        "candle": asdict(candle),
        "attempts": all_attempts,
        "preferred_rpc": selected_preferred,
    }


def select_verification_candidates(
    token_reports: list[dict[str, Any]],
) -> list[tuple[dict[str, str], Candle]]:
    candidates: list[tuple[float, dict[str, str], Candle]] = []
    for report in token_reports:
        token = report["token"]
        for window in report["windows"]:
            for raw in window["candles"]:
                candle = Candle(**raw)
                if candle.volume > 0:
                    candidates.append((candle.volume, token, candle))
    candidates.sort(key=lambda item: item[0], reverse=True)
    output: list[tuple[dict[str, str], Candle]] = []
    used_tokens: set[str] = set()
    for _, token, candle in candidates:
        if token["issuer"] in used_tokens:
            continue
        output.append((token, candle))
        used_tokens.add(token["issuer"])
    return output[:2]


def summarize_token(report: dict[str, Any]) -> dict[str, Any]:
    windows = report["windows"]
    nonempty = [w for w in windows if w["count"] > 0]
    positive = [w for w in windows if w["positive_volume_count"] > 0]
    count = sum(w["count"] for w in windows)
    positive_count = sum(w["positive_volume_count"] for w in windows)
    return {
        "name": report["token"]["name"],
        "issuer": report["token"]["issuer"],
        "md5": report["metadata"]["md5"],
        "metadata_identity_ok": report["metadata"]["identity_ok"],
        "window_count": len(windows),
        "nonempty_window_count": len(nonempty),
        "positive_window_count": len(positive),
        "candle_count": count,
        "positive_volume_candle_count": positive_count,
        "volume_sum": sum(w["volume_sum"] for w in windows),
        "qualified_for_model_stage": (
            len(nonempty) >= 3
            and len(positive) >= 3
            and count >= 120
            and positive_count >= 30
        ),
    }


def run(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = make_session()

    token_reports: list[dict[str, Any]] = []
    for token_source in TOKENS:
        token = dict(token_source)
        metadata = fetch_token_metadata(session, token, raw_dir)
        windows = [
            fetch_window(
                session,
                token,
                metadata["md5"],
                start_iso,
                end_iso,
                raw_dir,
            )
            for start_iso, end_iso in WINDOWS
        ]
        token_reports.append(
            {"token": token, "metadata": metadata, "windows": windows}
        )

    token_summaries = [summarize_token(report) for report in token_reports]
    qualified = {
        summary["issuer"] for summary in token_summaries
        if summary["qualified_for_model_stage"]
    }

    clio_checks: list[dict[str, Any]] = []
    preferred_rpc: tuple[str, str] | None = None
    for token, candle in select_verification_candidates(token_reports):
        if token["issuer"] not in qualified:
            continue
        check = verify_candle_on_clio(
            session, token, candle, preferred_rpc
        )
        preferred_raw = check.get("preferred_rpc")
        if (
            isinstance(preferred_raw, (list, tuple))
            and len(preferred_raw) == 2
        ):
            preferred_rpc = (str(preferred_raw[0]), str(preferred_raw[1]))
        clio_checks.append(check)
        if check["confirmed"]:
            write_json(
                output / f"CLIO_MATCH_{token['name'].upper().replace(' ', '_')}.json",
                check,
            )

    confirmed_issuers = {
        check["token"]["issuer"] for check in clio_checks if check["confirmed"]
    }
    source_gate_pass = bool(qualified & confirmed_issuers)
    decision = (
        "OPEN_FROZEN_PRE2024_MODEL_STAGE"
        if source_gate_pass
        else "CLOSE_XRPL_DEX_SOURCE_ROUTE_BEFORE_MARKET_OUTCOMES"
    )

    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "phase": "OUTCOME_SEALED_SOURCE_GATE",
        "source_gate_pass": source_gate_pass,
        "scientific_decision": decision,
        "source": {
            "historical_api": XRPL_TO_BASE,
            "official_rpc_endpoints": list(CLIO_ENDPOINTS),
            "interval": INTERVAL,
            "windows": list(WINDOWS),
            "tokens": [dict(token) for token in TOKENS],
        },
        "token_summaries": token_summaries,
        "qualified_issuers": sorted(qualified),
        "clio_confirmed_issuers": sorted(confirmed_issuers),
        "clio_checks": clio_checks,
        "bybit_market_opened": False,
        "future_return_opened": False,
        "model_fitted": False,
        "strategy_pnl_opened": False,
        "official_2024_opened": False,
        "official_2026_opened": False,
        "orders_submitted": False,
        "fatal_error": None,
    }
    write_json(output / "SOURCE_GATE_RESULT.json", result)

    manifest_files: list[dict[str, Any]] = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name not in {"SOURCE_MANIFEST.json", "OUTPUT_SHA256SUMS.txt"}:
            manifest_files.append(
                {
                    "path": str(path.relative_to(output)),
                    "sha256": sha256_bytes(path.read_bytes()),
                    "bytes": path.stat().st_size,
                }
            )
    manifest = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "files": manifest_files,
        "manifest_root": sha256_bytes(stable_json_bytes(manifest_files)),
    }
    write_json(output / "SOURCE_MANIFEST.json", manifest)
    return result


def self_test() -> None:
    assert token_md5("issuer", "USD") == hashlib.md5(b"issuer_USD").hexdigest()
    payload = {
        "data": {
            "ohlc": [
                [1640995200000, "0.8", "0.9", "0.7", "0.85", "123"],
                {
                    "timestamp": 1640996100,
                    "open": 0.85,
                    "high": 0.91,
                    "low": 0.84,
                    "close": 0.90,
                    "volume": 44,
                },
            ]
        }
    }
    candles, errors = parse_candles(payload)
    assert not errors
    assert len(candles) == 2
    assert candles[1].timestamp_ms == 1640996100000
    result = {
        "ledger_index": 123,
        "ledger_time": 1,
        "changes": [
            {
                "currency_a": "XRP_drops",
                "currency_b": "issuer/USD",
                "volume_a": "2500000",
                "volume_b": "2",
                "close": "1250000",
                "open": "1250000",
                "high": "1250000",
                "low": "1250000",
            }
        ],
    }
    matches = matching_book_change(result, "issuer", "USD")
    assert len(matches) == 1
    assert math.isclose(matches[0]["xrp_volume"], 2.5)
    assert math.isclose(matches[0]["xrp_per_token_close"], 1.25)
    assert find_identity({"token": {"issuer": "issuer", "currency": "USD"}}, "issuer", "USD")
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
            "scientific_decision": "CLOSE_XRPL_DEX_SOURCE_ROUTE_BEFORE_MARKET_OUTCOMES",
            "bybit_market_opened": False,
            "future_return_opened": False,
            "model_fitted": False,
            "strategy_pnl_opened": False,
            "official_2024_opened": False,
            "official_2026_opened": False,
            "orders_submitted": False,
            "fatal_error": repr(exc),
        }
        write_json(args.output / "SOURCE_GATE_RESULT.json", result)
        write_json(
            args.output / "SOURCE_MANIFEST.json",
            {
                "schema_version": 1,
                "claim_id": CLAIM_ID,
                "fatal_error": repr(exc),
            },
        )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
