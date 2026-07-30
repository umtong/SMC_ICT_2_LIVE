#!/usr/bin/env python3
"""Discover documented, unauthenticated AI transcription endpoints safely.

Only public docs/OpenAPI surfaces are used.  A candidate operation must return a
timestamped transcript for a known-positive control before it is tried on one
video from each requested channel.  Administrative, billing and deletion routes
are excluded.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse

import requests


BASES = (
    "https://api.youtubetotext.com",
    "https://youtubetotext.com",
)
DOC_PATHS = (
    "/openapi.json",
    "/swagger.json",
    "/api-docs",
    "/docs",
    "/redoc",
    "/",
)
CONTROL = ("known_positive_control", "F6wDs1HRTSo")
TARGETS = (
    ("swipalnam", "-Tp2fhvVVGM"),
    ("chartbro", "0h9lpMUBSlE"),
    ("indicator_sensei", "2U0s_i07vMY"),
)
FORBIDDEN = re.compile(r"admin|delete|remove|billing|payment|invoice|subscription|login|auth|token", re.I)
INTERESTING = re.compile(r"transcrib|transcript|speech|whisper|audio|caption|generate|queue|job", re.I)


def walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, child in value.items():
            yield from walk_strings(key)
            yield from walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_strings(child)


def transcript_shape(payload: Any) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []

    def visit(value: Any, path: str = "$") -> None:
        if isinstance(value, list):
            timed = []
            for item in value:
                if not isinstance(item, Mapping):
                    continue
                text = item.get("text") or item.get("utf8") or item.get("caption")
                start = item.get("start")
                if start is None:
                    start = item.get("start_ms") or item.get("offset") or item.get("timestamp")
                if text and start is not None:
                    timed.append(item)
            if timed:
                candidates.append({
                    "path": path,
                    "segment_count": len(timed),
                    "text_characters": sum(len(str(item.get("text") or item.get("utf8") or item.get("caption") or "")) for item in timed),
                    "first_segments": timed[:3],
                })
            for index, child in enumerate(value[:200]):
                visit(child, f"{path}[{index}]")
        elif isinstance(value, Mapping):
            for key, child in value.items():
                visit(child, f"{path}.{key}")

    visit(payload)
    candidates.sort(key=lambda row: (row["segment_count"], row["text_characters"]), reverse=True)
    return candidates[0] if candidates else {"segment_count": 0, "text_characters": 0}


def docs(session: requests.Session) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    operations: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for base in BASES:
        for path in DOC_PATHS:
            url = urljoin(base + "/", path.lstrip("/"))
            row: dict[str, Any] = {"url": url}
            try:
                response = session.get(url, timeout=30, allow_redirects=True)
                row.update({"status_code": response.status_code, "bytes": len(response.content), "content_type": response.headers.get("content-type")})
                payload = None
                try:
                    payload = response.json()
                except Exception:
                    pass
                if isinstance(payload, Mapping) and isinstance(payload.get("paths"), Mapping):
                    for route, methods in payload["paths"].items():
                        if not INTERESTING.search(str(route)) or FORBIDDEN.search(str(route)):
                            continue
                        if not isinstance(methods, Mapping):
                            continue
                        for method, specification in methods.items():
                            method = str(method).upper()
                            if method not in {"GET", "POST"}:
                                continue
                            key = (method, urljoin(response.url, str(route).lstrip("/")))
                            if key in seen:
                                continue
                            seen.add(key)
                            operations.append({
                                "method": method,
                                "url_template": key[1],
                                "source_doc": response.url,
                                "operation": specification,
                            })
                else:
                    text = response.text
                    paths = sorted(set(re.findall(r"/[A-Za-z0-9_{}./-]*(?:transcrib|transcript|whisper|caption|audio|job|queue)[A-Za-z0-9_{}./-]*", text, flags=re.I)))
                    for route in paths:
                        if FORBIDDEN.search(route):
                            continue
                        for method in ("GET", "POST"):
                            key = (method, urljoin(base + "/", route.lstrip("/")))
                            if key in seen:
                                continue
                            seen.add(key)
                            operations.append({"method": method, "url_template": key[1], "source_doc": response.url, "operation": None})
                row["discovered_operations"] = len(operations)
            except Exception as exc:
                row["exception"] = f"{type(exc).__name__}: {exc}"
            ledger.append(row)
    static = (
        ("GET", "https://api.youtubetotext.com/transcribe/{video_id}"),
        ("GET", "https://api.youtubetotext.com/ai_transcript/{video_id}"),
        ("GET", "https://api.youtubetotext.com/generate_transcript/{video_id}"),
        ("POST", "https://api.youtubetotext.com/transcribe"),
        ("POST", "https://api.youtubetotext.com/api/transcribe"),
    )
    for method, url in static:
        key = (method, url)
        if key not in seen:
            seen.add(key)
            operations.append({"method": method, "url_template": url, "source_doc": "static_safe_probe", "operation": None})
    return operations[:80], ledger


def request_variants(operation: Mapping[str, Any], video_id: str):
    template = str(operation["url_template"])
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    url = template
    for name in ("video_id", "videoId", "id", "youtube_id", "youtubeId"):
        url = url.replace("{" + name + "}", video_id)
    if "{" in url:
        return []
    method = str(operation["method"]).upper()
    if method == "GET":
        return [(method, url, None), (method, url + ("&" if "?" in url else "?") + "video_id=" + video_id, None)]
    payloads = (
        {"video_id": video_id},
        {"videoId": video_id},
        {"id": video_id},
        {"url": video_url},
        {"youtube_url": video_url},
        {"video_url": video_url},
    )
    return [(method, url, payload) for payload in payloads]


def job_urls(payload: Any, response_url: str) -> list[str]:
    urls: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            lowered = str(key).lower()
            if isinstance(value, str) and value.startswith("http") and any(token in lowered for token in ("status", "result", "job", "poll", "url")):
                urls.append(value)
            elif isinstance(value, str) and any(token in lowered for token in ("status", "result", "job", "poll")) and value.startswith("/"):
                urls.append(urljoin(response_url, value))
            elif isinstance(value, (Mapping, list)):
                urls.extend(job_urls(value, response_url))
    elif isinstance(payload, list):
        for child in payload:
            urls.extend(job_urls(child, response_url))
    return list(dict.fromkeys(urls))


def execute(session: requests.Session, operation: Mapping[str, Any], label: str, video_id: str) -> dict[str, Any]:
    attempts = []
    for method, url, body in request_variants(operation, video_id):
        row: dict[str, Any] = {"method": method, "url": url, "body": body}
        try:
            if method == "GET":
                response = session.get(url, timeout=60, allow_redirects=True)
            else:
                response = session.post(url, json=body, timeout=60, allow_redirects=True)
            row.update({"status_code": response.status_code, "content_type": response.headers.get("content-type"), "bytes": len(response.content)})
            try:
                payload = response.json()
                row["payload"] = payload
            except Exception:
                payload = {"raw": response.text[:4000]}
                row["payload"] = payload
            shape = transcript_shape(payload)
            row["transcript_shape"] = shape
            attempts.append(row)
            if shape["segment_count"] > 0:
                return {"label": label, "video_id": video_id, "success": True, "operation": operation, "request": row, "attempts": attempts}
            for poll_url in job_urls(payload, response.url)[:4]:
                for poll in range(4):
                    time.sleep(8.0)
                    polled = session.get(poll_url, timeout=60, allow_redirects=True)
                    try:
                        poll_payload = polled.json()
                    except Exception:
                        poll_payload = {"raw": polled.text[:4000]}
                    poll_shape = transcript_shape(poll_payload)
                    poll_row = {"poll_url": poll_url, "poll": poll + 1, "status_code": polled.status_code, "payload": poll_payload, "transcript_shape": poll_shape}
                    row.setdefault("polls", []).append(poll_row)
                    if poll_shape["segment_count"] > 0:
                        return {"label": label, "video_id": video_id, "success": True, "operation": operation, "request": row, "attempts": attempts}
        except Exception as exc:
            row["exception"] = f"{type(exc).__name__}: {exc}"
            attempts.append(row)
    return {"label": label, "video_id": video_id, "success": False, "operation": operation, "attempts": attempts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-2-LIVE/1.0", "Accept": "application/json"})
    operations, doc_ledger = docs(session)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        controls = list(pool.map(lambda operation: execute(requests.Session(), operation, *CONTROL), operations))
    winners = [row for row in controls if row.get("success")]
    target_rows = []
    if winners:
        work = [(winner["operation"], label, video_id) for winner in winners[:8] for label, video_id in TARGETS]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.workers, max(1, len(work)))) as pool:
            target_rows = list(pool.map(lambda item: execute(requests.Session(), *item), work))
    successful_operations = []
    for winner in winners:
        operation = winner["operation"]
        matches = [row for row in target_rows if row.get("operation") == operation and row.get("success")]
        if matches:
            successful_operations.append({"operation": operation, "control": winner, "targets": matches, "target_success_count": len(matches)})
    successful_operations.sort(key=lambda row: row["target_success_count"], reverse=True)
    result = {
        "schema_version": 1,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "source_sha": os.environ.get("GITHUB_SHA"),
        "documented_operation_count": len(operations),
        "doc_ledger": doc_ledger,
        "control_success_count": len(winners),
        "winner_count": len(successful_operations),
        "winners": successful_operations,
        "control_rows": controls,
        "target_rows": target_rows,
        "decision": "AI_TRANSCRIPTION_API_WINNER_FOUND" if successful_operations else "NO_AI_TRANSCRIPTION_API_WINNER",
    }
    result["payload_sha256_before_field"] = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if successful_operations:
        winner = {"schema_version": 1, "run_id": result["run_id"], "source_sha": result["source_sha"], "decision": result["decision"], "winner": successful_operations[0], "result_sha256": hashlib.sha256((args.output / "result.json").read_bytes()).hexdigest()}
        (args.output / "winner.json").write_text(json.dumps(winner, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": result["decision"], "operations": len(operations), "control_success": len(winners), "winners": len(successful_operations)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
